import * as THREE from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { createSweepWarningMarkers, warningSegmentCenters } from './sweep_warning_markers.js'
import { sweepSectionGeometry } from './sweep_cross_section.js'
import { createSweepLivePreview } from './sweep_live_preview.js'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

/** Display-only swept helix tubes, point picking and world translation controls. */
export function createSweepPreview(scene, { canvas, getCamera, getControls, addFrameCallback, removeFrameCallback, onSelect, onMove, onOrient, canOrient = () => true, setPreviewHelices = () => {} } = {}) {
  const root = new THREE.Group(), geometry = new THREE.Group(), points = new THREE.Group()
  root.name = 'sweep-preview'; points.name = 'sweep-control-points'; geometry.name = 'sweep-geometry'
  root.add(geometry, points); scene.add(root)
  const live = createSweepLivePreview(root)
  let liveFrame = null, pendingDraft = null
  const warnings = createSweepWarningMarkers(scene,{canvas,getCamera,addFrameCallback,removeFrameCallback})
  const hidden = new Map()
  function restoreScene() { setPreviewHelices([]); for (const [node, visible] of hidden) node.visible = visible; hidden.clear() }
  let mode = 'translate', pointBases = [], orientationBasis = new THREE.Matrix4()
  const arrows = new THREE.Group(); arrows.name = 'sweep-orientation-arrows'; root.add(arrows)
  const sections = new THREE.Group(); sections.name = 'sweep-cross-sections'; root.add(sections)
  let sectionShape = null, selectedShape = null
  const target = new THREE.Object3D(), raycaster = new THREE.Raycaster()
  target.name = 'sweep-point-target'
  const origin = new THREE.Vector3(), inverse = new THREE.Matrix3(), rotation = new THREE.Matrix3()
  let selected = 1, tc = null, helper = null, pointerId = null, orbit = null, orbitEnabled = true, hasFrame = false
  function disposeChildren(group) {
    for (const child of [...group.children]) {
      child.geometry?.dispose(); child.material?.dispose(); group.remove(child)
    }
  }
  function clearSections() {
    for (const child of [...sections.children]) { child.material.dispose(); sections.remove(child) }
    sectionShape?.dispose(); selectedShape?.dispose(); sectionShape = selectedShape = null
  }
  function clearGeometry() { if (liveFrame != null) cancelAnimationFrame(liveFrame); liveFrame = pendingDraft = null; live.reset(); geometry.visible = true; restoreScene(); disposeChildren(geometry); clearSections(); warnings.set([]) }
  function frameMatrix(b) { return new THREE.Matrix4().set(...b[0],0,...b[1],0,...b[2],0,0,0,0,1) }
  function anglesFromFrame(frame) {
    const e = new THREE.Euler().setFromRotationMatrix(orientationBasis.clone().invert().multiply(frame), 'YXZ')
    return [e.x,e.y,e.z].map(THREE.MathUtils.radToDeg)
  }
  function updateSection(index) {
    const section = sections.children[index]
    if (!section || !points.children[index]) return
    section.position.copy(points.children[index].position)
    if (pointBases[index]) section.quaternion.setFromRotationMatrix(frameMatrix(pointBases[index]))
    section.geometry = index === selected ? selectedShape : sectionShape
    section.material.color.setRGB(...(index === selected ? [1,.87,.50] : [.25,.7,.78]))
    section.material.opacity = 1
    section.renderOrder = index === selected ? 103 : 100
  }
  function endDrag() {
    if (pointerId != null) {
      tc?.pointerUp({ button: 0 })
      if (canvas?.hasPointerCapture?.(pointerId)) canvas.releasePointerCapture(pointerId)
      pointerId = null
    }
    if (orbit) orbit.enabled = orbitEnabled
    orbit = null
  }
  function clear() {
    hasFrame = false; mode = 'translate'; tc?.setMode(mode)
    endDrag(); tc?.detach(); clearGeometry(); disposeChildren(points); disposeChildren(arrows)
  }
  function ensureControls() {
    if (tc || !canvas || !getCamera?.()) return
    scene.add(target)
    tc = new TransformControls(getCamera(), canvas)
    // Route capture-phase events ourselves so scene selection and OrbitControls
    // cannot consume a point/handle drag before TransformControls receives it.
    tc.disconnect(); tc.setMode(mode); tc.setRotationSnap(null); tc.setSpace('world'); tc.setSize(.65)
    helper = tc.getHelper(); helper.name = 'sweep-point-gizmo'; scene.add(helper)
    tc.addEventListener('objectChange', () => {
      const point = points.children[selected]
      if (!point) return
      if (mode === 'rotate') {
        if (!canOrient(selected)) return
        const frame = new THREE.Matrix4().makeRotationFromQuaternion(target.quaternion)
        pointBases[selected] = [0,1,2].map(r => [0,1,2].map(c => frame.elements[c*4+r]))
        updateSection(selected)
        onOrient?.(selected, anglesFromFrame(frame))
        return
      }
      if (selected === 0) return
      point.position.copy(target.position)
      updateSection(selected)
      const offset = target.position.clone().sub(origin).applyMatrix3(inverse)
      onMove?.(selected, offset.toArray())
    })
  }
  function select(index) {
    selected = index
    for (const [i, point] of points.children.entries()) point.material.color.setHex(i === index ? 0xffffff : i === 0 ? 0x58a6ff : 0xffc857)
    sections.children.forEach((_, i) => updateSection(i))
    if (points.children[index] && (mode === 'translate' ? index > 0 : canOrient(index))) {
      ensureControls()
      if (!tc?.dragging) {
        target.position.copy(points.children[index].position)
        if (pointBases[index]) target.quaternion.setFromRotationMatrix(frameMatrix(pointBases[index]))
      }
      tc?.attach(target)
    } else tc?.detach()
  }
  function syncCamera() { if (tc && getCamera?.()) tc.camera = getCamera() }
  function setPoints(values, index = selected) {
    if (!hasFrame) return
    while (points.children.length > values.length) {
      const child = points.children.at(-1)
      child.geometry.dispose(); child.material.dispose(); points.remove(child)
    }
    values.forEach((p, i) => {
      let point = points.children[i]
      if (!point) {
        point = new THREE.Mesh(new THREE.SphereGeometry(.55, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffc857, depthTest: false, depthWrite: false }))
        point.name = `sweep-point-${i}`; point.userData.pointIndex = i; point.renderOrder = 101
        points.add(point)
      }
      point.visible = p.every(Number.isFinite)
      if (point.visible) point.position.fromArray(p).applyMatrix3(rotation).add(origin)
    })
    select(index)
    if (!points.children[index]?.visible) tc?.detach()
  }
  function pointer(event) {
    const rect = canvas.getBoundingClientRect()
    return { x: (event.clientX - rect.left) / rect.width * 2 - 1, y: -(event.clientY - rect.top) / rect.height * 2 + 1, button: event.button }
  }
  function consume(event) { event.preventDefault(); event.stopImmediatePropagation() }
  function down(event) {
    if (event.target !== canvas || event.button !== 0 || !points.children.length) return
    syncCamera(); scene.updateMatrixWorld(true); getCamera().updateMatrixWorld(true)
    const p = pointer(event)
    // A visible point wins over a gizmo handle behind it, including the fixed origin.
    raycaster.setFromCamera(p, getCamera())
    const hit = raycaster.intersectObjects(points.children.filter(p => p.visible), false)[0]
    if (hit) { onSelect?.(hit.object.userData.pointIndex); consume(event); return }
    if (!tc?.object) return
    helper.updateMatrixWorld(true); tc.pointerHover(p)
    if (!tc.axis) return
    tc.pointerDown(p)
    if (!tc.dragging) return
    pointerId = event.pointerId; canvas.setPointerCapture?.(pointerId)
    orbit = getControls?.(); orbitEnabled = orbit?.enabled ?? true
    if (orbit) orbit.enabled = false
    consume(event)
  }
  function move(event) {
    if (pointerId !== null) { tc.pointerMove(pointer(event)); consume(event) }
    else if (event.target === canvas && tc?.object) { syncCamera(); tc.pointerHover(pointer(event)) }
  }
  function keydown(event) {
    const from = event.target
    const inPointList = from?.closest?.('.sweep-point')
    if (event.key !== 'Tab' || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey || event.repeat ||
        !hasFrame || !points.children[selected] || pointerId !== null ||
        (!inPointList && from !== canvas && from?.tagName !== 'BODY')) return
    if (mode === 'translate' && !canOrient(selected)) return
    consume(event); ensureControls(); mode = mode === 'translate' ? 'rotate' : 'translate'
    tc?.setMode(mode); tc?.setSpace(mode === 'rotate' ? 'local' : 'world'); tc?.setRotationSnap(null)
    select(selected)
    if (mode === 'rotate' && pointBases[selected]) onOrient?.(selected, anglesFromFrame(frameMatrix(pointBases[selected])))
    canvas?.focus({ preventScroll: true })
  }
  function up(event) { if (pointerId !== null) { endDrag(); consume(event) } }
  if (canvas) {
    window.addEventListener('keydown', keydown, true)
    window.addEventListener('pointerdown', down, true)
    window.addEventListener('pointermove', move, true)
    window.addEventListener('pointerup', up, true)
    window.addEventListener('pointercancel', up, true)
    window.addEventListener('blur', endDrag)
    addFrameCallback?.(syncCamera)
  }
  return {
    update(data, draft) {
      clearGeometry()
      if (!data) { clear(); return }
      origin.fromArray(data.origin_nm ?? data.points_nm[0])
      rotation.set(...(data.point_rotation ?? [[1,0,0],[0,1,0],[0,0,1]]).flat())
      inverse.copy(rotation).invert()
      hasFrame = true
      live.setBaseline(data, draft)
      pointBases = data.point_bases ?? []
      if (tc?.dragging && mode === 'rotate') {
        const frame = new THREE.Matrix4().makeRotationFromQuaternion(target.quaternion)
        pointBases[selected] = [0,1,2].map(r => [0,1,2].map(c => frame.elements[c*4+r]))
      }
      if (data.edit_backbones_nm) {
        const affected = new Set(data.edit_helix_ids ?? [])
        setPreviewHelices([...affected])
        scene.getObjectByName('sweep-warning-icons-saved')?.children.forEach(icon => {
          if (icon.userData.helixIds?.some(id => affected.has(id))) {
            hidden.set(icon, icon.visible); icon.visible = false
          }
        })
        for (const path of data.edit_backbones_nm) {
          const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(path.map(p => new THREE.Vector3(...p))),
            new THREE.LineBasicMaterial({ color: 0x80d9b0 }))
          line.name = 'sweep-edited-backbone'; geometry.add(line)
        }
      }
      const cells = data.cross_section_nm ?? []
      if (cells.length) {
        // Keep the outer footprint at every point; bound interior-ring detail
        // for unusually large drafts, retaining all rings at the selection.
        sectionShape = sweepSectionGeometry(cells, Math.max(1,Math.ceil(cells.length*pointBases.length/8192)))
        selectedShape = sweepSectionGeometry(cells)
        pointBases.forEach((_,i) => {
          const section = new THREE.LineSegments(sectionShape, new THREE.LineBasicMaterial({color:new THREE.Color().setRGB(.25,.7,.78),depthTest:false,depthWrite:false}))
          section.name = `sweep-cross-section-${i}`; sections.add(section)
        })
      }
      orientationBasis.set(...[...(data.orientation_basis?.[0] ?? [1,0,0]),0,...(data.orientation_basis?.[1] ?? [0,1,0]),0,...(data.orientation_basis?.[2] ?? [0,0,1]),0,0,0,0,1])
      disposeChildren(arrows)
      pointBases.forEach((basis, i) => {
        const at = new THREE.Vector3(...data.points_nm[i])
        for (const [axis, color, length] of [[2, 0x62ed9b, 4], [0, 0xffc857, 2]]) {
          const end = at.clone().addScaledVector(new THREE.Vector3(basis[0][axis], basis[1][axis], basis[2][axis]), length)
          const delta = end.clone().sub(at).normalize(), side = new THREE.Vector3().crossVectors(delta, new THREE.Vector3(0,1,0))
          if (side.lengthSq() < .01) side.crossVectors(delta, new THREE.Vector3(1,0,0))
          side.normalize().multiplyScalar(.35)
          const back = end.clone().addScaledVector(delta,-.7)
          const vertices = [at,end,end,back.clone().add(side),end,back.clone().sub(side)]
          arrows.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(vertices), new THREE.LineBasicMaterial({ color, depthTest: false })))
        }
      })
      warnings.set(warningSegmentCenters(data.path_nm,data.feasibility?.warning_segments ?? []))
      const warningVertices = []
      for (const i of data.feasibility?.warning_segments ?? []) if (data.path_nm[i+1]) warningVertices.push(new THREE.Vector3(...data.path_nm[i]), new THREE.Vector3(...data.path_nm[i+1]))
      if (warningVertices.length) {
        const warning = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(warningVertices), new THREE.LineBasicMaterial({ color: 0xff5d3d, depthTest: false }))
        warning.name = 'sweep-curvature-warning'; warning.renderOrder = 105; geometry.add(warning)
        // A narrow tube keeps the warning visible on high-DPI displays where
        // WebGL's one-pixel line width can disappear among the helix ghosts.
        const pieces = []
        for (let i = 0; i < warningVertices.length; i += 2) {
          const a = warningVertices[i], b = warningVertices[i+1]
          if (a.distanceToSquared(b) > 1e-16) {
            const piece = new THREE.CylinderGeometry(.10,.10,a.distanceTo(b),6)
            const turn = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),b.clone().sub(a).normalize())
            piece.applyQuaternion(turn); piece.translate(...a.clone().add(b).multiplyScalar(.5).toArray()); pieces.push(piece)
          }
        }
        if (pieces.length) {
          const highlight = new THREE.Mesh(mergeGeometries(pieces), new THREE.MeshBasicMaterial({color:0xff5d3d,depthTest:false,depthWrite:false}))
          highlight.renderOrder=104; geometry.add(highlight); pieces.forEach(p => p.dispose())
        }
      }
      const path = new THREE.BufferGeometry().setFromPoints(data.path_nm.map(p => new THREE.Vector3(...p)))
      geometry.add(new THREE.Line(path, new THREE.LineBasicMaterial({ color: 0x58a6ff, depthTest: false })))
      for (const [i, axis] of (data.helix_paths_nm ?? []).entries()) {
        if (data.edit_helix_ids && !data.edit_helix_ids.includes(data.helix_path_ids?.[i])) continue
        // A piecewise-linear curve preserves the exact server samples; do not
        // interpolate a second spline with a different shape for the ghost.
        const curve = new THREE.CurvePath()
        for (let i = 1; i < axis.length; i++) {
          const a = new THREE.Vector3(...axis[i - 1]), b = new THREE.Vector3(...axis[i])
          if (a.distanceToSquared(b) > 1e-16) curve.add(new THREE.LineCurve3(a, b))
        }
        const shape = curve.curves.length ? new THREE.TubeGeometry(curve, curve.curves.length, 1, 8, false) : new THREE.SphereGeometry(1, 12, 8)
        const mesh = new THREE.Mesh(shape,
          new THREE.MeshBasicMaterial({ color: 0x58a6ff, transparent: true, opacity: .22, depthWrite: false }))
        if (!curve.curves.length && axis.length) mesh.position.fromArray(axis[0])
        geometry.add(mesh)
      }
      setPoints(data.points_nm.map(p => new THREE.Vector3(...p).sub(origin).applyMatrix3(inverse).toArray()))
    },
    updateDraft(values, angles, index = selected) {
      if (!hasFrame) return
      setPoints(values, index)
      pendingDraft = {values, angles}
      if (liveFrame != null) return
      liveFrame = requestAnimationFrame(() => {
        liveFrame = null
        const draft = pendingDraft; pendingDraft = null
        const sampled = live.update(draft.values, draft.angles)
        if (!sampled) return
        geometry.visible = false; warnings.set([])
        pointBases = sampled.pointFrames.map(q => {
          const m = new THREE.Matrix4().makeRotationFromQuaternion(q)
          return [0,1,2].map(r => [0,1,2].map(c => m.elements[c*4+r]))
        })
        // Refresh existing section and arrow buffers; no tube tessellation per drag.
        sections.children.forEach((_,i) => updateSection(i))
        pointBases.forEach((basis,i) => {
          const at = points.children[i]?.position
          if (!at) return
          for (const [slot,axis,length] of [[0,2,4],[1,0,2]]) {
            const arrow = arrows.children[i*2+slot]; if (!arrow) continue
            const direction = new THREE.Vector3(...basis.map(r=>r[axis]))
            const end = at.clone().addScaledVector(direction,length)
            const side = new THREE.Vector3().crossVectors(direction,new THREE.Vector3(0,1,0))
            if (side.lengthSq()<.01) side.crossVectors(direction,new THREE.Vector3(1,0,0))
            side.normalize().multiplyScalar(.35)
            const back = end.clone().addScaledVector(direction,-.7)
            const positions = arrow.geometry.attributes.position
            ;[at,end,end,back.clone().add(side),end,back.clone().sub(side)].forEach((p,k)=>positions.setXYZ(k,p.x,p.y,p.z))
            positions.needsUpdate = true; arrow.frustumCulled = false
          }
        })
      })
    },
    getOrientation(index) {
      const b = pointBases[index]; return b ? anglesFromFrame(frameMatrix(b)) : [0,0,0]
    },
    getMode: () => mode,
    select, setPoints, clear, clearGeometry,
    dispose() {
      clear(); live.dispose(); warnings.dispose(); tc?.dispose(); helper?.removeFromParent(); target.removeFromParent(); scene.remove(root)
      window.removeEventListener('keydown', keydown, true)
      window.removeEventListener('pointerdown', down, true); window.removeEventListener('pointermove', move, true)
      window.removeEventListener('pointerup', up, true); window.removeEventListener('pointercancel', up, true)
      window.removeEventListener('blur', endDrag); removeFrameCallback?.(syncCamera)
    },
  }
}
