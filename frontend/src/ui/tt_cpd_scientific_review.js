/** Help ▸ TT-CPD Scientific Review — hash-pinned, gate-neutral 3D reviewer. */

import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'

const ELEMENT_COLORS = { H: 0xd8dee9, C: 0x657bff, N: 0x58a6ff, O: 0xf85149, P: 0xd29922 }
const REVIEW_COLORS = {
  ordinary: 0x6e7681,
  cyclobutane_ring: 0xd29922,
  photoproduct_crosslink: 0xff4fd8,
  closest_contact: 0xf85149,
  terminal_cap: 0x3fb950,
  phosphate_boundary: 0xffa657,
  glycosidic_boundary: 0xa371f7,
}

export function focusBondStyle(kind) {
  if (kind === 'photoproduct_crosslink') return { color: '#ff4fd8', radius: 0.105, label: 'new CPD crosslink' }
  if (kind === 'cyclobutane_ring') return { color: '#d29922', radius: 0.085, label: 'reduced C5–C6 ring bond' }
  if (kind === 'terminal_cap') return { color: '#3fb950', radius: 0.085, label: 'terminal cap' }
  if (kind === 'phosphate_boundary') return { color: '#ffa657', radius: 0.08, label: 'phosphate boundary' }
  if (kind === 'glycosidic_boundary') return { color: '#a371f7', radius: 0.075, label: 'glycosidic boundary' }
  return { color: '#6e7681', radius: 0.045, label: 'model bond' }
}

export function reviewDecisionPayload({ stage, scene, decision, reviewer, notes, partition }) {
  return {
    stage,
    product_id: scene.product_id,
    conformer_id: ['coupled_conformer', 'dna_boundary_model'].includes(stage) ? scene.conformer_id : null,
    decision,
    partition: decision === 'approve' && stage === 'coupled_conformer' ? partition : null,
    reviewer: reviewer.trim(),
    notes: notes.trim(),
  }
}

export function reviewScopeMessage() {
  return 'Visual identity review only. Approval confirms atom mapping, connectivity, endpoint order and stereochemistry; it does not validate charges or force constants, release a force field, or enable NAMD.'
}

function _bondCylinder(a, b, radius, material) {
  const vector = new THREE.Vector3().subVectors(b, a)
  const length = vector.length()
  if (length < 1e-7) return null
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(radius, radius, length, 12, 1, false),
    material,
  )
  mesh.position.copy(a).addScaledVector(vector, 0.5)
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), vector.normalize())
  return mesh
}

function _createViewer(container) {
  const width = Math.max(620, container.clientWidth || 760)
  const height = 500
  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(window.devicePixelRatio || 1)
  renderer.setSize(width, height)
  renderer.setClearColor(0x0d1117, 1)
  renderer.domElement.style.cssText = 'display:block;width:100%;height:500px'
  container.append(renderer.domElement)

  const labelLayer = el('div', { attrs: {
    style: 'position:absolute;inset:0;pointer-events:none;overflow:hidden',
    'aria-hidden': 'true',
  } })
  container.append(labelLayer)
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(42, width / height, 0.01, 500)
  scene.add(new THREE.HemisphereLight(0xffffff, 0x1b2230, 1.25))
  const key = new THREE.DirectionalLight(0xffffff, 1.2)
  key.position.set(4, 5, 7)
  scene.add(key)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  const molecule = new THREE.Group()
  scene.add(molecule)
  let labels = []
  let alive = true
  let hideHydrogens = false

  function disposeMolecule() {
    molecule.traverse(object => {
      object.geometry?.dispose?.()
      const materials = Array.isArray(object.material) ? object.material : [object.material]
      materials.forEach(material => material?.dispose?.())
    })
    molecule.clear()
    labelLayer.replaceChildren()
    labels = []
  }

  function addLabel(text, position, color = '#e6edf3', emphasis = false, offset = [0, 0]) {
    const node = el('div', { text, attrs: { style:
      `position:absolute;transform:translate(-50%,-50%);padding:2px 4px;border-radius:3px;` +
      `background:rgba(13,17,23,.88);border:1px solid ${color};color:${color};` +
      `font:${emphasis ? '600 ' : ''}10px var(--font-mono,monospace);white-space:nowrap`,
    } })
    labelLayer.append(node)
    labels.push({ node, position, offset })
  }

  function setScene(data) {
    disposeMolecule()
    const center = new THREE.Vector3()
    const points = data.coordinates_angstrom.map(([x, y, z]) => new THREE.Vector3(x, y, z))
    points.forEach(point => center.add(point))
    center.divideScalar(Math.max(points.length, 1))
    points.forEach(point => point.sub(center))
    const stereoIndices = new Set((data.stereocenters || []).map(item => item.atom_index))

    let crosslinkLabelIndex = 0
    data.bonds.forEach(bond => {
      if (hideHydrogens && bond.indices.some(index => data.elements[index] === 'H')) return
      const style = focusBondStyle(bond.kind)
      const material = new THREE.MeshPhongMaterial({ color: REVIEW_COLORS[bond.kind] ?? REVIEW_COLORS.ordinary, shininess: 55 })
      const mesh = _bondCylinder(points[bond.indices[0]], points[bond.indices[1]], style.radius, material)
      if (mesh) molecule.add(mesh)
      if (['photoproduct_crosslink', 'terminal_cap'].includes(bond.kind)) {
        const midpoint = points[bond.indices[0]].clone().add(points[bond.indices[1]]).multiplyScalar(0.5)
        const endpoint = bond.atoms.some(atom => atom.startsWith('1:')) ? -1 : 1
        const offset = bond.kind === 'photoproduct_crosslink'
          ? [0, crosslinkLabelIndex++ % 2 === 0 ? -68 : 68]
          : [endpoint * 58, 0]
        addLabel(`${bond.atoms[0]} — ${bond.atoms[1]}`, midpoint, style.color, true, offset)
      }
    })
    points.forEach((point, index) => {
      if (hideHydrogens && data.elements[index] === 'H') return
      const stereo = stereoIndices.has(index)
      const geometry = new THREE.SphereGeometry(
        stereo ? 0.25 : data.elements[index] === 'H' ? 0.11 : 0.19,
        18,
        13,
      )
      const material = new THREE.MeshPhongMaterial({
        color: stereo ? 0x39d0d8 : (ELEMENT_COLORS[data.elements[index]] ?? 0xa5d6ff),
        emissive: stereo ? 0x0f4d52 : 0x000000,
        shininess: 75,
      })
      const atom = new THREE.Mesh(geometry, material)
      atom.position.copy(point)
      molecule.add(atom)
    })
    ;(data.stereocenters || []).forEach((centerRecord, centerIndex) => {
      const configuration = centerRecord.configuration ? ` ${centerRecord.configuration}` : ''
      const sign = centerRecord.expected_sign ? ` · ${centerRecord.expected_sign}` : ''
      const endpoint = centerRecord.atom.startsWith('1:') ? -1 : 1
      const row = centerRecord.atom.endsWith(':C5') ? -36 : 36
      addLabel(
        `${centerRecord.atom}${configuration}${sign}`,
        points[centerRecord.atom_index], '#39d0d8', true, [endpoint * 108, row],
      )
    })

    const contact = data.metadata?.geometry_audit?.closest_nonbonded_pair
    if (contact?.atoms?.length === 2) {
      const indices = contact.atoms.map(atom => data.atom_keys.indexOf(atom))
      if (indices.every(index => index >= 0)) {
        const geometry = new THREE.BufferGeometry().setFromPoints([points[indices[0]], points[indices[1]]])
        const line = new THREE.Line(geometry, new THREE.LineDashedMaterial({ color: REVIEW_COLORS.closest_contact, dashSize: 0.18, gapSize: 0.12 }))
        line.computeLineDistances()
        molecule.add(line)
        const midpoint = points[indices[0]].clone().add(points[indices[1]]).multiplyScalar(0.5)
        addLabel(`closest contact ${Number(contact.distance_angstrom).toFixed(2)} Å`, midpoint, '#f85149', false, [0, 38])
      }
    }

    const radius = Math.max(2, ...points.map(point => point.length()))
    const distance = radius / Math.tan(camera.fov * Math.PI / 360) * 1.18
    camera.position.set(distance * 0.72, distance * 0.35, distance)
    camera.lookAt(0, 0, 0)
    controls.target.set(0, 0, 0)
    controls.update()
  }

  function resetView() {
    const box = new THREE.Box3().setFromObject(molecule)
    const size = box.getSize(new THREE.Vector3()).length() || 6
    camera.position.set(size, size * 0.4, size)
    camera.lookAt(0, 0, 0)
    controls.target.set(0, 0, 0)
    controls.update()
  }

  function render() {
    if (!alive) return
    controls.update()
    renderer.render(scene, camera)
    for (const label of labels) {
      const projected = label.position.clone().project(camera)
      label.node.style.left = `${(projected.x * 0.5 + 0.5) * renderer.domElement.clientWidth + label.offset[0]}px`
      label.node.style.top = `${(-projected.y * 0.5 + 0.5) * renderer.domElement.clientHeight + label.offset[1]}px`
      label.node.style.display = projected.z > -1 && projected.z < 1 ? 'block' : 'none'
    }
    requestAnimationFrame(render)
  }
  render()
  return {
    setScene,
    resetView,
    setHideHydrogens(value, data) { hideHydrogens = value; setScene(data) },
    dispose() { alive = false; disposeMolecule(); controls.dispose(); renderer.dispose(); renderer.domElement.remove(); labelLayer.remove() },
  }
}

function _metricSummary(scene) {
  const audit = scene.metadata?.geometry_audit
  const caps = scene.metadata?.caps_and_protonation
  if (caps) {
    const crosslinks = scene.metadata?.crosslink_distances ?? {}
    return [
      `Source: RCSB 1N4E chain ${scene.metadata?.source_selection?.chain ?? '?'}`,
      `Formal charge: ${scene.metadata?.formal_charge}`,
      `Chirality audit: ${scene.metadata?.chirality_passed ? 'PASS' : 'FAIL'}`,
      `C5–C5 / C6–C6: ${Number(crosslinks.c5_c5_angstrom).toFixed(3)} / ${Number(crosslinks.c6_c6_angstrom).toFixed(3)} Å`,
      `5′ cap: ${caps.five_prime}`,
      `3′ cap: ${caps.three_prime}`,
      `Phosphate: ${caps.inter_residue_phosphodiester}`,
      `Bases: ${caps.tautomer}`,
    ]
  }
  if (!audit) return [
    `Frequency evidence: ${scene.metadata?.frequency_status ?? 'not reported'}`,
    `Mirror operation used: ${scene.metadata?.mirror_operation_used === false ? 'NO' : String(scene.metadata?.mirror_operation_used)}`,
  ]
  const contact = audit.closest_nonbonded_pair
  return [
    `Chirality audit: ${scene.metadata?.chirality_passed ? 'PASS' : 'FAIL'}`,
    `Proper-rotation RMSD: ${Number(audit.proper_rotation_aligned_rmsd_angstrom).toFixed(4)} Å`,
    `Bond ratio range: ${Number(audit.minimum_graph_bond_ratio).toFixed(4)} – ${Number(audit.maximum_graph_bond_ratio).toFixed(4)}`,
    contact ? `Closest nonbonded: ${contact.atoms.join(' / ')} · ${Number(contact.distance_angstrom).toFixed(3)} Å` : 'Closest nonbonded: unavailable',
  ]
}

export async function showTTCpdScientificReview({ api, viewerFactory = _createViewer }) {
  const body = el('div', { attrs: { style: 'min-height:620px' } })
  const modal = createModal({
    title: 'TT-CPD scientific review',
    size: 'xl',
    className: 'modal--cpd-review',
    body,
    actions: [createButton({ label: 'Close', variant: 'primary', onClick: () => modal.close() })],
    onClose: () => viewer?.dispose(),
  })
  let viewer = null
  modal.open()
  body.append(el('div', { text: 'Loading and verifying Archive-drive review evidence…', attrs: { style: 'color:#8b949e' } }))
  let catalog
  try {
    catalog = await api.getPhotoproductScientificReview()
  } catch (error) {
    body.replaceChildren(el('div', { text: `Review evidence rejected: ${error?.message ?? error}`, attrs: { style: 'color:#f85149' } }))
    return modal
  }

  body.replaceChildren()
  body.append(el('div', { text: reviewScopeMessage(), attrs: {
    style: 'padding:8px 10px;margin-bottom:10px;border:1px solid #d29922;border-radius:5px;background:#2d2414;color:#f2cc60;font-size:12px;line-height:1.4',
  } }))
  const toolbar = el('div', { attrs: { style: 'display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap' } })
  const stageSelect = el('select', { attrs: { style: 'background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:5px' } })
  stageSelect.append(
    new Option('Chemical definition (7 candidates)', 'chemical_definition'),
    new Option('DNA boundary model (2 crystal copies)', 'dna_boundary_model'),
    new Option('Coupled conformers (8 × 4)', 'coupled_conformer'),
  )
  const productSelect = el('select', { attrs: { style: 'min-width:230px;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:5px' } })
  const conformerSelect = el('select', { attrs: { style: 'background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:5px' } })
  const reset = createButton({ label: 'Reset view', onClick: () => viewer?.resetView() })
  const nextUnresolved = createButton({ label: 'Next unresolved', onClick: () => showNextUnresolved() })
  const progress = el('span', { attrs: { style: 'font:11px var(--font-mono,monospace);color:#8b949e' } })
  const hydrogens = el('label', { attrs: { style: 'color:#8b949e;font-size:11px;margin-left:auto' }, children: [
    el('input', { attrs: { type: 'checkbox' } }), ' Hide hydrogens',
  ] })
  toolbar.append(stageSelect, productSelect, conformerSelect, reset, nextUnresolved, progress, hydrogens)
  body.append(toolbar)

  const layout = el('div', { attrs: { style: 'display:grid;grid-template-columns:minmax(620px,1.7fr) minmax(270px,.8fr);gap:12px' } })
  const canvasWrap = el('div', { attrs: { style: 'position:relative;height:500px;border:1px solid #30363d;border-radius:6px;overflow:hidden;background:#0d1117' } })
  const panel = el('div', { attrs: { style: 'display:flex;flex-direction:column;gap:9px;min-width:0' } })
  layout.append(canvasWrap, panel)
  body.append(layout)
  try {
    viewer = viewerFactory(canvasWrap)
  } catch (error) {
    canvasWrap.append(el('div', { text: `WebGL viewer unavailable: ${error?.message ?? error}`, attrs: { style: 'padding:20px;color:#f85149' } }))
  }

  const title = el('div', { attrs: { style: 'font-weight:650;color:#e6edf3;font-size:14px' } })
  const legend = el('div', { attrs: { style: 'font-size:11px;line-height:1.7;color:#c9d1d9' }, html:
    '<span style="color:#ff4fd8">● CPD crosslinks</span><br><span style="color:#d29922">● C5–C6 ring bonds</span><br><span style="color:#39d0d8">● audited stereocenters</span><br><span style="color:#3fb950">● terminal caps</span><br><span style="color:#ffa657">● phosphate boundary</span><br><span style="color:#a371f7">● glycosidic bonds</span><br><span style="color:#f85149">-- closest nonbonded contact</span>',
  })
  const metrics = el('div', { attrs: { style: 'font:11px/1.55 var(--font-mono,monospace);color:#8b949e;padding:7px;background:#0d1117;border-radius:4px;white-space:pre-wrap' } })
  const current = el('div', { attrs: { style: 'font-size:11px;color:#8b949e' } })
  const reviewer = el('input', { attrs: { placeholder: 'Reviewer name', autocomplete: 'name', style: 'background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:6px' } })
  const partition = el('select', { attrs: { style: 'background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:6px' } })
  partition.append(new Option('Training partition', 'training'), new Option('Validation partition', 'validation'))
  const notes = el('textarea', { attrs: { placeholder: 'Required: what you checked, and why this decision is appropriate', rows: 5, style: 'resize:vertical;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:6px;font:11px var(--font-ui,sans-serif)' } })
  const status = el('div', { attrs: { role: 'status', style: 'min-height:18px;font-size:11px;color:#8b949e' } })
  const decisionButtons = el('div', { attrs: { style: 'display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px' } })
  panel.append(title, legend, metrics, current, reviewer, partition, notes, decisionButtons, status)

  let activeScene = null
  let stage = 'chemical_definition'

  async function save(decision) {
    if (!activeScene) return
    const payload = reviewDecisionPayload({
      stage, scene: activeScene, decision, reviewer: reviewer.value,
      notes: notes.value, partition: partition.value,
    })
    status.textContent = 'Saving hash-pinned visual review decision…'
    status.style.color = '#8b949e'
    try {
      const result = await api.putPhotoproductScientificReviewDecision(payload)
      activeScene.decision = result.decision
      status.textContent = decision === 'revise'
        ? 'Revision requested. This target remains unresolved and gate-blocking.'
        : `Saved ${decision}. This visual decision does not release parameters.`
      status.style.color = decision === 'approve' ? '#3fb950' : decision === 'reject' ? '#f85149' : '#d29922'
      renderDecision()
      updateProgress()
    } catch (error) {
      status.textContent = `Decision rejected: ${error?.message ?? error}`
      status.style.color = '#f85149'
    }
  }
  for (const [decision, label, variant] of [['approve', 'Approve', 'primary'], ['reject', 'Reject', 'danger'], ['revise', 'Revise', 'secondary']]) {
    const button = createButton({ label, variant, onClick: () => save(decision) })
    button.dataset.reviewDecision = decision
    decisionButtons.append(button)
  }

  function renderDecision() {
    const decision = activeScene?.decision
    if (!decision) {
      current.style.color = '#8b949e'
      current.textContent = 'No visual review decision recorded.'
      return
    }
    if (decision.stale) {
      current.style.color = '#f2cc60'
      current.textContent = `STALE ${decision.decision.toUpperCase()} by ${decision.reviewer}: ${decision.stale_reason}`
      reviewer.value = decision.reviewer ?? reviewer.value
      notes.value = decision.notes ?? ''
      return
    }
    current.style.color = '#8b949e'
    current.textContent = `Current: ${decision.decision.toUpperCase()} by ${decision.reviewer} · ${decision.reviewed_at}`
    reviewer.value = decision.reviewer ?? reviewer.value
    notes.value = decision.notes ?? ''
    if (decision.partition) partition.value = decision.partition
  }

  function sceneOptions() {
    if (stage === 'chemical_definition') return catalog.definition_scenes.map(scene => ({ id: scene.product_id, label: scene.product_id }))
    if (stage === 'dna_boundary_model') return catalog.boundary_scenes.map(scene => ({
      id: scene.conformer_id,
      label: `${scene.product_id} · RCSB chain ${scene.metadata?.source_selection?.chain}`,
    }))
    return catalog.conformer_groups.map(group => ({ id: group.product_id, label: group.product_id }))
  }

  function stageScenes() {
    if (stage === 'chemical_definition') return catalog.definition_scenes
    if (stage === 'dna_boundary_model') return catalog.boundary_scenes
    return catalog.conformer_groups.flatMap(group => group.frames)
  }

  function updateProgress() {
    const scenes = stageScenes()
    const completed = scenes.filter(scene => scene.decision && !scene.decision.stale).length
    const stale = scenes.filter(scene => scene.decision?.stale).length
    progress.textContent = `${completed}/${scenes.length} current${stale ? ` · ${stale} stale` : ''}`
  }

  function showNextUnresolved() {
    const target = stageScenes().find(scene => !scene.decision || scene.decision.stale)
    if (!target) {
      status.textContent = 'Every item in this stage has a current decision.'
      status.style.color = '#3fb950'
      return
    }
    if (stage === 'chemical_definition') {
      productSelect.value = target.product_id
    } else if (stage === 'dna_boundary_model') {
      productSelect.value = target.conformer_id
    } else {
      productSelect.value = target.product_id
      populateConformers()
      conformerSelect.value = target.conformer_id
    }
    showScene()
  }

  function populateProducts() {
    productSelect.replaceChildren(...sceneOptions().map(item => new Option(item.label, item.id)))
    conformerSelect.style.display = stage === 'coupled_conformer' ? '' : 'none'
    partition.style.display = stage === 'coupled_conformer' ? '' : 'none'
    populateConformers()
    updateProgress()
  }

  function populateConformers() {
    conformerSelect.replaceChildren()
    if (stage === 'coupled_conformer') {
      const group = catalog.conformer_groups.find(item => item.product_id === productSelect.value)
      conformerSelect.append(...(group?.frames ?? []).map(frame => new Option(`${frame.conformer_id} · ${frame.metadata.source_candidate_id}`, frame.conformer_id)))
    }
    showScene()
  }

  function showScene() {
    if (stage === 'chemical_definition') {
      activeScene = catalog.definition_scenes.find(scene => scene.product_id === productSelect.value)
    } else if (stage === 'dna_boundary_model') {
      activeScene = catalog.boundary_scenes.find(scene => scene.conformer_id === productSelect.value)
    } else {
      const group = catalog.conformer_groups.find(item => item.product_id === productSelect.value)
      activeScene = group?.frames.find(frame => frame.conformer_id === conformerSelect.value)
    }
    if (!activeScene) return
    title.textContent = stage === 'chemical_definition'
      ? `${activeScene.product_id} · ${activeScene.metadata.stereochemistry}`
      : stage === 'dna_boundary_model'
        ? `${activeScene.product_id} · DNA boundary ${activeScene.conformer_id}`
        : `${activeScene.product_id} · ${activeScene.conformer_id}`
    metrics.textContent = _metricSummary(activeScene).join('\n')
    status.textContent = ''
    renderDecision()
    updateProgress()
    viewer?.setScene(activeScene)
  }

  stageSelect.addEventListener('change', () => { stage = stageSelect.value; populateProducts() })
  productSelect.addEventListener('change', populateConformers)
  conformerSelect.addEventListener('change', showScene)
  hydrogens.querySelector('input').addEventListener('change', event => viewer?.setHideHydrogens(event.target.checked, activeScene))
  populateProducts()
  return modal
}
