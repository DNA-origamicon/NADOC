import * as THREE from 'three'
import { createMultiColorGlowLayer } from './glow_layer.js'
import { initProteinGizmo } from './protein_gizmo.js'
import { primaryRefOfKind } from './selection_model.js'
import { deferrableContextMenu } from './right_click_menu.js'
import { patchNanoparticle, deleteNanoparticle } from '../api/client.js'
import { promptGoldNanosphereDiameter } from '../ui/nanoparticle_dialog.js'
import { addStreptavidinCoating, addBiotinMarkers, applyCoatingTransforms } from './streptavidin_renderer.js'
import { nanoparticleRenderInputsChanged } from './nanoparticle_render_dependencies.js'
import { createStreptavidinAtomicRenderer } from './streptavidin_atomic_renderer.js'
import { openStreptavidinDialog } from '../ui/streptavidin_dialog.js'

const GOLD = 0xd4af37

function poseMatrix(particle) {
  const values = particle?.pose?.values ?? particle?.pose
  const matrix = new THREE.Matrix4()
  if (Array.isArray(values) && values.length === 16) matrix.fromArray(values).transpose()
  return matrix
}

export function initNanoparticleSubsystem({ scene, store, controls, camera, canvas, selectionController, designRenderer = null, rightSidebar = null, openConjugateManager = null }) {
  const root = new THREE.Group()
  root.name = 'nanoparticles'
  scene.add(root)
  const connectorRoot = new THREE.Group(); connectorRoot.name = 'nanoparticle-connections'; scene.add(connectorRoot)
  const linkerAtomRoot = new THREE.Group(); linkerAtomRoot.name = 'nanoparticle-linker-atoms'; linkerAtomRoot.visible = false; scene.add(linkerAtomRoot)
  const meshes = new Map()
  let representation = 'full'
  let coatingTransforms = {}
  let highlighted = null
  let moveRotatePanel = null
  let liveHelixIds = []
  let livePivot = null
  let movementConstraints = new Map()

  const material = new THREE.MeshPhysicalMaterial({
    color: GOLD, metalness: 1, roughness: 0.18, clearcoat: 0.45,
    clearcoatRoughness: 0.12, envMapIntensity: 1.35,
  })
  const selectedMaterial = material.clone()
  selectedMaterial.emissive.setHex(0x5b4300)
  const dotMaterials = new Map()
  const dotGlows = new Map()
  let fluorescenceOn = false
  let goldQuenching = new Map()
  function particleMaterial(particle, selected) {
    if (particle.kind !== 'quantum_dot') return selected ? selectedMaterial : material
    const color = particle.quantum_dot?.display_color ?? '#58d65d'
    const key = particle.id
    if (!dotMaterials.has(key)) dotMaterials.set(key, new THREE.MeshPhysicalMaterial({
      color, metalness: 0, roughness: 0.3, clearcoat: 0.35,
      emissive: color, emissiveIntensity: fluorescenceOn ? 1.5 : selected ? 0.5 : 0.12,
      toneMapped: !fluorescenceOn,
    }))
    const mat = dotMaterials.get(key)
    mat.color.set(color)
    mat.emissive.set(color)
    mat.emissiveIntensity = fluorescenceOn ? 1.5 * (goldQuenching.get(particle.id)?.brightness ?? 1) : selected ? 0.5 : 0.12
    if (mat.toneMapped !== !fluorescenceOn) { mat.toneMapped = !fluorescenceOn; mat.needsUpdate = true }
    return mat
  }

  function refreshAppearance() {
    const id = primaryRefOfKind(store.getState(), 'nanoparticle')?.id ?? null
    for (const particle of store.getState().currentDesign?.nanoparticles ?? []) {
      const mesh = meshes.get(particle.id)
      if (!mesh) continue
      mesh.material = particleMaterial(particle, particle.id === id)
      if (particle.kind !== 'quantum_dot') continue
      if (fluorescenceOn) {
        if (!dotGlows.has(particle.id)) dotGlows.set(particle.id, createMultiColorGlowLayer(mesh))
        dotGlows.get(particle.id).setEntries([{
          pos: new THREE.Vector3(),
          emissionColor: mesh.material.emissive.getHex(),
          scale: particle.diameter_nm * 2.5,
          brightness: goldQuenching.get(particle.id)?.brightness ?? 1,
        }])
        // Halos are attached to the particle, so live previews move them too.
        // Only the physical sphere participates in selection/raycasting.
        for (const child of mesh.children) child.raycast = () => {}
      } else {
        dotGlows.get(particle.id)?.clear()
        dotGlows.delete(particle.id)
      }
    }
  }

  // The shared panel is composed before this subsystem and can temporarily be
  // rebound by other selection subscribers.  Keep the nanoparticle gizmo as a
  // direct participant in the actual UI buttons so Apply can never fall
  // through to a cluster action while an NP is visibly attached.
  document.getElementById('mr-apply-btn')?.addEventListener('click', () => {
    if (gizmo?.isAttached?.()) gizmo.commit?.()
  })
  document.getElementById('mr-cancel-btn')?.addEventListener('click', () => {
    if (gizmo?.isAttached?.()) gizmo.cancel?.()
  })
  document.getElementById('mr-reset-btn')?.addEventListener('click', () => {
    if (gizmo?.isAttached?.()) gizmo.reset?.()
  })

  function rebuild() {
    for (const glow of dotGlows.values()) glow.clear()
    dotGlows.clear()
    for (const mesh of meshes.values()) {
      mesh.userData.strepAtoms?.dispose()
      root.remove(mesh); mesh.geometry.dispose()
      for (const child of mesh.children) if (['streptavidin-coating', 'biotin-pockets'].includes(child.name)) child.traverse(obj => { obj.geometry?.dispose(); obj.material?.dispose() })
    }
    meshes.clear()
    const ids = new Set((store.getState().currentDesign?.nanoparticles ?? []).map(p => p.id))
    for (const [id, mat] of dotMaterials) {
      if (!ids.has(id)) { mat.dispose(); dotMaterials.delete(id) }
    }
    connectorRoot.clear(); linkerAtomRoot.clear()
    for (const particle of store.getState().currentDesign?.nanoparticles ?? []) {
      if (!particle.visible) continue
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(particle.diameter_nm / 2, 48, 32),
        particleMaterial(particle, particle.id === highlighted))
      mesh.name = `${particle.kind === 'quantum_dot' ? 'quantum-dot' : 'gold-nanosphere'}:${particle.id}`
      mesh.userData.nanoparticleId = particle.id
      mesh.userData.nanoparticleKind = particle.kind
      if (particle.kind !== 'quantum_dot') mesh.userData.photoMaterialKind = 'gold-nanoparticle'
      mesh.applyMatrix4(poseMatrix(particle))
      addStreptavidinCoating(mesh, particle.coating)
      if (particle.coating) {
        mesh.userData.strepAtoms = createStreptavidinAtomicRenderer(mesh, particle.coating)
        mesh.userData.strepAtoms.setMode(representation)
        mesh.getObjectByName('streptavidin-coating').visible = !['vdw', 'ballstick', 'stick'].includes(representation)
      }
      addBiotinMarkers(mesh, particle, representation, store.getState().currentGeometry ?? [])
      if (particle.coating) applyCoatingTransforms(mesh, particle, coatingTransforms)
      root.add(mesh)
      meshes.set(particle.id, mesh)
    }
    const design = store.getState().currentDesign
    const geometry = store.getState().currentGeometry ?? []
    const particlesById = new Map((design?.nanoparticles ?? []).map(p => [p.id, p]))
    movementConstraints = new Map()
    for (const particle of design?.nanoparticles ?? []) {
      const applied = (design.nanoparticle_connection_versions ?? []).filter(v => v.nanoparticle_id === particle.id && v.applied)
      if (applied.length !== 1) continue
      const version = applied[0]
      const conjugation = (design.nanoparticle_conjugations ?? []).find(c => c.nanoparticle_id === particle.id)
      const record = conjugation?.surface_strands?.find(r => r.strand_id === version.strand_id)
      const ohNucs = geometry.filter(n => n.overhang_id === version.overhang_id)
      const tip = ohNucs.find(n => n.is_five_prime || n.is_three_prime) ?? ohNucs[0]
      const rootNuc = tip && ohNucs.reduce((best, n) =>
        Math.abs((n.bp_index ?? 0) - (tip.bp_index ?? 0)) > Math.abs((best.bp_index ?? 0) - (tip.bp_index ?? 0)) ? n : best, tip)
      if (!record || !rootNuc?.backbone_position) continue
      const rootPoint = new THREE.Vector3(...(version.constraint_root_nm ?? rootNuc.backbone_position))
      const jointPoint = record.backbone_attachment_local_nm
        ? new THREE.Vector3(...record.backbone_attachment_local_nm).applyMatrix4(poseMatrix(particle))
        : new THREE.Vector3(...record.site_local)
          .multiplyScalar(particle.diameter_nm / 2 + (conjugation.spacer_nm ?? 0))
          .applyMatrix4(poseMatrix(particle))
      const handleNucs = geometry.filter(n => n.strand_id === version.strand_id)
      const handleJointNuc = handleNucs.find(n => conjugation.attach_end === '3p' ? n.is_three_prime : n.is_five_prime)
      const rigidJoint = handleJointNuc?.backbone_position
        ? new THREE.Vector3(...handleJointNuc.backbone_position) : jointPoint
      const cluster = (design.cluster_transforms ?? []).find(c => c.overhang_duplex_driver_id === version.overhang_id)
      movementConstraints.set(particle.id, {
        mode: 'two_ball_joint', root: rootPoint.toArray(), joint: jointPoint.toArray(),
        radius_nm: version.constraint_radius_nm ?? rootPoint.distanceTo(rigidJoint),
        helix_id: cluster?.helix_ids?.[0] ?? rootNuc.helix_id,
        domain_ids: cluster?.domain_ids ?? [], overhang_id: version.overhang_id,
      })
    }
    for (const conjugation of design?.nanoparticle_conjugations ?? []) {
      const particle = particlesById.get(conjugation.nanoparticle_id); if (!particle) continue
      const matrix = poseMatrix(particle), radius = particle.diameter_nm / 2
      for (const record of conjugation.surface_strands ?? []) {
        const dir = new THREE.Vector3(...record.site_local)
        const sulfur = dir.clone().multiplyScalar(radius).applyMatrix4(matrix)
        const strandNucs = geometry.filter(n => n.strand_id === record.strand_id)
        const rootNuc = strandNucs.find(n => conjugation.attach_end === '3p' ? n.is_three_prime : n.is_five_prime)
          ?? strandNucs[0]
        // Terminate the visible surface tether on the ACTUAL emitted backbone
        // bead. Applied handles may be far from their radial preview position;
        // using the nominal spacer endpoint left a visibly detached line.
        const dna = rootNuc?.backbone_position
          ? new THREE.Vector3(...rootNuc.backbone_position)
          : dir.clone().multiplyScalar(radius + conjugation.spacer_nm).applyMatrix4(matrix)
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([sulfur, dna]), new THREE.LineBasicMaterial({ color: 0x66c7ff }))
        line.userData = { nanoparticleId: particle.id, strandId: record.strand_id,
          sulfurPosition: sulfur.toArray(), backbonePosition: dna.toArray(),
          measuredLengthNm: sulfur.distanceTo(dna) }; connectorRoot.add(line)
        const steps = Math.max(1, Math.round(conjugation.spacer_nm / .35))
        const atomPositions = []
        for (let i = 0; i <= steps; i++) {
          const t = i / steps, isSulfur = i === 0
          const atom = new THREE.Mesh(new THREE.SphereGeometry(isSulfur ? .18 : .12, 10, 7), new THREE.MeshStandardMaterial({ color: isSulfur ? 0xffd43b : (conjugation.scheme.includes('peg') && i % 3 === 0 ? 0xff4040 : 0x777777) }))
          atom.name = isSulfur ? `np-thiol-sulfur:${record.strand_id}` : `np-linker-atom:${record.strand_id}:${i}`
          atom.position.lerpVectors(sulfur, dna, t); atom.userData = { element: isSulfur ? 'S' : (conjugation.scheme.includes('peg') && i % 3 === 0 ? 'O' : 'C'), strandId: record.strand_id }
          atomPositions.push(atom.position.clone()); linkerAtomRoot.add(atom)
        }
        const surfaceInside = dir.clone().multiplyScalar(Math.max(0, radius - .22)).applyMatrix4(matrix)
        const bondPoints = [surfaceInside, atomPositions[0]]
        for (let i = 1; i < atomPositions.length; i++) bondPoints.push(atomPositions[i - 1], atomPositions[i])
        const bonds = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(bondPoints), new THREE.LineBasicMaterial({ color: 0xd8d8d8 }))
        bonds.name = `np-thiol-linker-bonds:${record.strand_id}`
        bonds.userData = { strandId: record.strand_id, surfaceAttachment: true }
        linkerAtomRoot.add(bonds)
      }
    }
    for (const version of design?.nanoparticle_connection_versions ?? []) {
      if (!version.applied) continue
      const strandNucs = geometry.filter(n => n.strand_id === version.strand_id)
      const overhangNucs = geometry.filter(n => n.overhang_id === version.overhang_id)
      if (!strandNucs.length || !overhangNucs.length) continue
      const particle = particlesById.get(version.nanoparticle_id)
      if (!particle) continue
      const center = new THREE.Vector3().setFromMatrixPosition(poseMatrix(particle))
      const sourceNuc = strandNucs.reduce((best, n) => {
        const p = new THREE.Vector3(...n.backbone_position)
        return !best || p.distanceToSquared(center) > best.distance ? { n, distance: p.distanceToSquared(center) } : best
      }, null)?.n
      const targetNuc = overhangNucs.find(n => n.is_five_prime || n.is_three_prime) ?? overhangNucs[overhangNucs.length - 1]
      if (!sourceNuc || !targetNuc) continue
      const source = new THREE.Vector3(...sourceNuc.backbone_position)
      const target = new THREE.Vector3(...targetNuc.backbone_position)
      const midpoint = source.clone().lerp(target, .5)
      const chord = target.clone().sub(source)
      const bend = new THREE.Vector3(0, 1, 0).cross(chord)
      if (bend.lengthSq() < 1e-8) bend.set(1, 0, 0)
      midpoint.addScaledVector(bend.normalize(), Math.min(5, chord.length() * .15))
      const points = new THREE.QuadraticBezierCurve3(source, midpoint, target).getPoints(32)
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({ color: version.relaxed ? 0x3fb950 : 0xffffff }))
      line.name = `nanoparticle-overhang-connection:${version.id}`
      line.userData = { nanoparticleId: version.nanoparticle_id, strandId: version.strand_id,
        overhangId: version.overhang_id, versionId: version.id }
      connectorRoot.add(line)
    }
    syncSelection(true)
  }

  function centroid(id) {
    const mesh = meshes.get(id)
    return mesh?.getWorldPosition(new THREE.Vector3()) ?? null
  }

  const gizmo = initProteinGizmo(store, controls, {
    patchAttachment: patchNanoparticle,
    noun: 'Nanoparticle',
    onCommitted: () => { liveHelixIds = []; livePivot = null; rebuild() },
    onCancelled: () => {
      if (liveHelixIds.length && livePivot) {
        designRenderer?.applyClusterTransform?.(
          liveHelixIds, livePivot, livePivot, new THREE.Quaternion(),
        )
      }
      liveHelixIds = []; livePivot = null; rebuild()
    },
    onLiveStart: id => {
      meshes.get(id)?.updateMatrixWorld(true)
      liveHelixIds = (store.getState().currentDesign?.nanoparticle_conjugations ?? [])
        .filter(item => item.nanoparticle_id === id)
        .flatMap(item => item.surface_strands ?? [])
        .filter(item => !item.bound_overhang_id)
        .map(item => item.helix_id)
      livePivot = centroid(id)
      if (liveHelixIds.length) designRenderer?.captureClusterBase?.(liveHelixIds)
      const constraint = movementConstraints.get(id)
      if (constraint?.helix_id) designRenderer?.getHelixCtrl?.()?.captureClusterBase(
        [constraint.helix_id], constraint.domain_ids?.length ? constraint.domain_ids : null,
      )
    },
    onLive: (matrix, detail) => {
      const mesh = meshes.get(gizmo.getAttachmentId())
      if (mesh) {
        mesh.matrix.copy(matrix).multiply(poseMatrix(store.getState().currentDesign?.nanoparticles?.find(p => p.id === mesh.userData.nanoparticleId)))
        mesh.matrixAutoUpdate = false
      }
      if (liveHelixIds.length && detail?.pivot && detail?.position && detail?.rotation) {
        designRenderer?.applyClusterTransform?.(
          liveHelixIds, detail.pivot, detail.position, detail.rotation,
        )
      }
      const constraint = detail?.constraint
      if (constraint?.helix_id && detail.constrainedJoint) {
        const rootPoint = new THREE.Vector3(...constraint.root)
        const initial = new THREE.Vector3(...constraint.joint).sub(rootPoint)
        const current = detail.constrainedJoint.clone().sub(rootPoint)
        if (initial.lengthSq() > 1e-24 && current.lengthSq() > 1e-24) {
          const swing = new THREE.Quaternion().setFromUnitVectors(initial.normalize(), current.normalize())
          designRenderer?.getHelixCtrl?.()?.applyClusterTransform(
            [constraint.helix_id], rootPoint, rootPoint, swing,
            constraint.domain_ids?.length ? constraint.domain_ids : null,
          )
        }
      }
    },
    onLiveEnd: () => {},
  })

  function syncSelection(reanchor = false) {
    const id = primaryRefOfKind(store.getState(), 'nanoparticle')?.id ?? null
    highlighted = id
    const particles = store.getState().currentDesign?.nanoparticles ?? []
    refreshAppearance()
    if (id && meshes.has(id)) {
      if (reanchor || gizmo.getAttachmentId() !== id) gizmo.attach(
        id, scene, camera, canvas, centroid(id), movementConstraints.get(id) ?? null,
      )
      moveRotatePanel?.setProteinController?.(gizmo)
      moveRotatePanel?.setSessionMode?.('protein')
      moveRotatePanel?.setTransformValues?.(0, 0, 0, 0, 0, 0)
      rightSidebar?.open?.('properties')
      const panel = document.getElementById('move-rotate-panel')
      if (panel) { panel.style.display = ''; panel.dataset.nanoparticleActive = 'true' }
      const selectionBox = document.getElementById('mr-current-selection')
      const particle = particles.find(p => p.id === id)
      if (selectionBox) selectionBox.textContent = `${particle?.kind === 'quantum_dot'
        ? `Quantum dot · ${particle.quantum_dot?.product_name ?? ''}` : 'Gold nanosphere'} · ${id}`
      const hint = document.getElementById('mr-session-hint')
      if (hint) hint.textContent = movementConstraints.has(id)
        ? 'Drag the nanoparticle joint. The handle duplex swings rigidly between two ball joints.'
        : 'Drag the nanoparticle gizmo. Press T or R to change mode.'
    } else if (gizmo.isAttached()) gizmo.cancel()
    if (!id) {
      if (moveRotatePanel?.getProteinController?.() === gizmo) {
        moveRotatePanel.setProteinController(null)
      }
      const panel = document.getElementById('move-rotate-panel')
      if (panel?.dataset.nanoparticleActive === 'true') {
        panel.style.display = 'none'
        delete panel.dataset.nanoparticleActive
      }
    }
  }

  function pickAt(event) {
    const rect = canvas.getBoundingClientRect()
    const ndc = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    )
    const raycaster = new THREE.Raycaster()
    raycaster.setFromCamera(ndc, camera)
    return raycaster.intersectObjects([...meshes.values()], false)[0]?.object ?? null
  }

  canvas.addEventListener('contextmenu', deferrableContextMenu(canvas, event => {
    const mesh = pickAt(event)
    if (!mesh) return
    event.preventDefault(); event.stopPropagation()
    const id = mesh.userData.nanoparticleId
    selectionController.replace([{ kind: 'nanoparticle', id }])
    document.querySelector('.nanoparticle-context-menu')?.remove()
    const menu = document.createElement('div')
    menu.className = 'context-menu nanoparticle-context-menu'
    menu.style.cssText = `position:fixed;left:${event.clientX}px;top:${event.clientY}px;z-index:10000`
    let onOutside = null
    const dismiss = () => {
      menu.remove()
      if (onOutside) document.removeEventListener('pointerdown', onOutside, true)
    }
    const add = (label, action, disabled = false) => {
      const button = document.createElement('button')
      button.className = 'context-menu-item'
      button.textContent = label
      button.disabled = disabled
      button.style.cssText = 'display:block;width:100%;padding:6px 16px;border:0;background:#23262b;color:#e6e6e6;text-align:left;white-space:nowrap;cursor:pointer'
      if (disabled) button.style.cssText += ';color:#777;cursor:not-allowed'
      button.onclick = async () => { if (disabled) return; dismiss(); await action() }
      menu.appendChild(button)
    }
    const particle = store.getState().currentDesign?.nanoparticles?.find(p => p.id === id)
    const isDot = particle?.kind === 'quantum_dot'
    add(isDot ? 'Edit scene diameter…' : 'Edit diameter…', async () => {
      const current = particle?.diameter_nm
      const title = isDot
        ? `Edit ${particle.quantum_dot?.product_name ?? 'quantum dot'} scene diameter (${particle.quantum_dot?.diameter_range_nm?.join('–')} nm)`
        : 'Edit gold nanosphere diameter'
      const diameter = await promptGoldNanosphereDiameter({ current, title })
      if (diameter != null && diameter !== current) await patchNanoparticle(id, { diameter_nm: diameter })
    })
    if (isDot) add('Streptavidin coating…', () => openStreptavidinDialog(particle))
    if (!isDot) add('Conjugate Manager…', () => openConjugateManager?.(id))
    add('Delete', () => deleteNanoparticle(id))
    document.body.appendChild(menu)
    onOutside = event => {
      if (menu.contains(event.target)) return
      dismiss()
    }
    // Delay registration so the contextmenu gesture that opened the menu cannot
    // immediately dismiss it. A pointerdown INSIDE must survive through click;
    // removing the button on pointerdown prevents its click handler from firing.
    setTimeout(() => document.addEventListener('pointerdown', onOutside, true), 0)
  }, { capture: true }), { capture: true })

  store.subscribe((next, prev) => {
    // Persisted metadata and identical geometry responses must retain the PDB
    // prototype and compiled materials. Actual placement/topology edits rebuild.
    if (nanoparticleRenderInputsChanged(next, prev)) rebuild()
    else if (next.selection !== prev.selection) syncSelection()
  })
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && primaryRefOfKind(store.getState(), 'nanoparticle')) {
      selectionController.clear()
    }
  }, { capture: true })
  window.addEventListener('nadoc:representation-change', event => {
    // Atomistic representations now receive real C3-thiol/phosphodiester atoms
    // from the backend model.  Keep this legacy overlay hidden or it would draw a
    // second, non-topological linker on top of the simulation structure.
    linkerAtomRoot.visible = false
    representation = event.detail?.representation ?? representation
    for (const mesh of meshes.values()) {
      const group = mesh.getObjectByName('biotin-pockets')
      if (group) group.visible = representation === 'full'
      mesh.userData.strepAtoms?.setMode(representation)
      const trace = mesh.getObjectByName('streptavidin-coating')
      if (trace) trace.visible = !['vdw', 'ballstick', 'stick'].includes(representation)
    }
  })
  window.addEventListener('nadoc:coating-oxdna-transforms', event => {
    coatingTransforms = event.detail ?? {}
    for (const particle of store.getState().currentDesign?.nanoparticles ?? []) {
      const mesh = meshes.get(particle.id)
      if (mesh && particle.coating) applyCoatingTransforms(mesh, particle, coatingTransforms)
    }
  })
  rebuild()
  return {
    root, meshes, gizmo, rebuild, connectorRoot, linkerAtomRoot,
    setFluorescence(on) {
      fluorescenceOn = Boolean(on)
      refreshAppearance()
    },
    getQuenchingParticles() {
      return (store.getState().currentDesign?.nanoparticles ?? []).map(particle => ({
        ...particle,
        // Live gizmo transforms take precedence over the saved pose. Visibility
        // is a view setting, so hidden gold remains physically present.
        pos: meshes.has(particle.id) ? meshes.get(particle.id).getWorldPosition(new THREE.Vector3())
          : root.localToWorld(new THREE.Vector3().setFromMatrixPosition(poseMatrix(particle))),
      }))
    },
    setGoldQuenching(results) {
      const next = new Map(results.map(result => [result.donor.id, result]))
      let changed = next.size !== goldQuenching.size
      for (const [id, result] of next) {
        if (result.brightness !== goldQuenching.get(id)?.brightness) changed = true
        const mesh = meshes.get(id)
        if (mesh) mesh.userData.goldQuenching = { brightness: result.brightness, incomplete: result.incomplete }
      }
      for (const id of goldQuenching.keys()) if (!next.has(id)) {
        const mesh = meshes.get(id)
        if (mesh) delete mesh.userData.goldQuenching
      }
      goldQuenching = next
      if (changed) refreshAppearance()
    },
    raycastPick(raycaster) {
      const hit = raycaster.intersectObjects([...meshes.values()], false)[0]
      return hit ? { distance: hit.distance, id: hit.object.userData.nanoparticleId } : null
    },
    select: id => selectionController.replace([{ kind: 'nanoparticle', id }]),
    setMoveRotatePanel(panel) { moveRotatePanel = panel; syncSelection() },
  }
}
