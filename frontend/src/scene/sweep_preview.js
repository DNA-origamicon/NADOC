import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

/** Display-only swept helix tubes, point picking and world translation controls. */
export function createSweepPreview(scene, { canvas, getCamera, getControls, addFrameCallback, removeFrameCallback, onSelect, onMove } = {}) {
  const root = new THREE.Group(), geometry = new THREE.Group(), points = new THREE.Group()
  root.name = 'sweep-preview'; points.name = 'sweep-control-points'; geometry.name = 'sweep-geometry'
  root.add(geometry, points); scene.add(root)
  const target = new THREE.Object3D(), raycaster = new THREE.Raycaster()
  target.name = 'sweep-point-target'
  const origin = new THREE.Vector3(), inverse = new THREE.Matrix3(), rotation = new THREE.Matrix3()
  let selected = 1, tc = null, helper = null, pointerId = null, orbit = null, orbitEnabled = true, hasFrame = false
  function disposeChildren(group) {
    for (const child of [...group.children]) {
      child.geometry?.dispose(); child.material?.dispose(); group.remove(child)
    }
  }
  function clearGeometry() { disposeChildren(geometry) }
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
    hasFrame = false
    endDrag(); tc?.detach(); clearGeometry(); disposeChildren(points)
  }
  function ensureControls() {
    if (tc || !canvas || !getCamera?.()) return
    scene.add(target)
    tc = new TransformControls(getCamera(), canvas)
    // Route capture-phase events ourselves so scene selection and OrbitControls
    // cannot consume a point/handle drag before TransformControls receives it.
    tc.disconnect(); tc.setMode('translate'); tc.setSpace('world'); tc.setSize(.65)
    helper = tc.getHelper(); helper.name = 'sweep-point-gizmo'; scene.add(helper)
    tc.addEventListener('objectChange', () => {
      const point = points.children[selected]
      if (!point || selected === 0) return
      point.position.copy(target.position)
      const offset = target.position.clone().sub(origin).applyMatrix3(inverse)
      onMove?.(selected, offset.toArray().map(v => Math.round(v * 1000) / 1000))
    })
  }
  function select(index) {
    selected = index
    for (const [i, point] of points.children.entries()) point.material.color.setHex(i === index ? 0xffffff : i === 0 ? 0x58a6ff : 0xffc857)
    if (index > 0 && points.children[index]) {
      ensureControls()
      if (!tc?.dragging) target.position.copy(points.children[index].position)
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
  function up(event) { if (pointerId !== null) { endDrag(); consume(event) } }
  if (canvas) {
    window.addEventListener('pointerdown', down, true)
    window.addEventListener('pointermove', move, true)
    window.addEventListener('pointerup', up, true)
    window.addEventListener('pointercancel', up, true)
    window.addEventListener('blur', endDrag)
    addFrameCallback?.(syncCamera)
  }
  return {
    update(data) {
      clearGeometry()
      if (!data) { clear(); return }
      origin.fromArray(data.origin_nm ?? data.points_nm[0])
      rotation.set(...(data.point_rotation ?? [[1,0,0],[0,1,0],[0,0,1]]).flat())
      inverse.copy(rotation).invert()
      hasFrame = true
      const path = new THREE.BufferGeometry().setFromPoints(data.path_nm.map(p => new THREE.Vector3(...p)))
      geometry.add(new THREE.Line(path, new THREE.LineBasicMaterial({ color: 0x58a6ff, depthTest: false })))
      for (const axis of data.helix_paths_nm ?? []) {
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
    select, setPoints, clear, clearGeometry,
    dispose() {
      clear(); tc?.dispose(); helper?.removeFromParent(); target.removeFromParent(); scene.remove(root)
      window.removeEventListener('pointerdown', down, true); window.removeEventListener('pointermove', move, true)
      window.removeEventListener('pointerup', up, true); window.removeEventListener('pointercancel', up, true)
      window.removeEventListener('blur', endDrag); removeFrameCallback?.(syncCamera)
    },
  }
}
