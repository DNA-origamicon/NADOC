/** Temporary Join pose. Never patches authored geometry during a drag. */
import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

export function createJoinMovement({ scene, canvas, getCamera, getControls, getAxes, getClusters, getSites, onChange }) {
  const root = new THREE.Group(); root.name = 'join-free-movement'; scene.add(root)
  const ghost = new THREE.Group(), hints = new THREE.Group(), target = new THREE.Object3D()
  ghost.name = 'join-free-ghost'; hints.name = 'join-proximity-hints'; root.add(ghost, hints, target)
  let tc = null, helper = null, cluster = null, center = new THREE.Vector3(), mode = 'translate', orbit = null, orbitEnabled = true
  let pose = { world_translation: [0, 0, 0], world_rotation: [0, 0, 0, 1] }
  const clear = group => { group.traverse(o => { o.geometry?.dispose(); o.material?.dispose() }); group.clear() }
  function releaseOrbit() { if (orbit) orbit.enabled = orbitEnabled; orbit = null }
  function ensureControls() {
    if (tc) return
    tc = new TransformControls(getCamera(), canvas); helper = tc.getHelper(); helper.name = 'join-movement-gizmo'; scene.add(helper)
    tc.addEventListener('dragging-changed', event => {
      if (event.value) { orbit = getControls?.(); orbitEnabled = orbit?.enabled ?? true; if (orbit) orbit.enabled = false }
      else releaseOrbit()
    })
    tc.addEventListener('objectChange', () => {
      const translation = target.position.clone().sub(center.clone().applyQuaternion(target.quaternion))
      pose = { world_translation: translation.toArray(), world_rotation: target.quaternion.toArray() }
      ghost.position.copy(translation); ghost.quaternion.copy(target.quaternion)
      onChange(pose)
    })
  }
  function attach(id) {
    detach(); cluster = getClusters().find(c => c.cluster_id === id)
    if (!cluster) return false
    const box = new THREE.Box3()
    for (const id of cluster.helix_ids ?? []) {
      const axis = getAxes()[id]
      const points = (axis?.samples?.length > 1 ? axis.samples : axis ? [axis.start, axis.end] : []).map(p => new THREE.Vector3(...p))
      if (points.length < 2) continue
      points.forEach(p => box.expandByPoint(p))
      const curve = new THREE.CurvePath()
      for (let i = 1; i < points.length; i++) if (points[i].distanceToSquared(points[i-1]) > 1e-12) curve.add(new THREE.LineCurve3(points[i-1], points[i]))
      if (!curve.curves.length) continue
      ghost.add(new THREE.Mesh(new THREE.TubeGeometry(curve, Math.min(1024, Math.max(16, points.length*3)), 1.04, 8),
        new THREE.MeshBasicMaterial({ color: 0x60d7ff, transparent: true, opacity: 0.45, depthWrite: false })))
    }
    if (box.isEmpty()) { detach(); return false }
    box.getCenter(center); target.position.copy(center); target.quaternion.identity()
    ensureControls(); tc.camera = getCamera(); tc.setMode(mode); tc.attach(target); tc.enabled = true
    root.visible = true; onChange(pose); return true
  }
  function detach() {
    tc?.detach(); if (tc) tc.enabled = false
    releaseOrbit(); clear(ghost); clear(hints); ghost.position.set(0, 0, 0); ghost.quaternion.identity()
    cluster = null; root.visible = false
    pose = { world_translation: [0, 0, 0], world_rotation: [0, 0, 0, 1] }
  }
  function showHints(reach, fixedId) {
    clear(hints)
    if (!cluster) return 0
    const rotation = new THREE.Quaternion(...pose.world_rotation), translation = new THREE.Vector3(...pose.world_translation)
    const moving = getSites().filter(s => s.cluster_id === cluster.cluster_id)
    const fixed = getSites().filter(s => s.cluster_id !== cluster.cluster_id && (!fixedId || s.cluster_id === fixedId))
    const pairs = []
    for (const q of moving) {
      const point = new THREE.Vector3(...q.position).applyQuaternion(rotation).add(translation)
      const normal = new THREE.Vector3(...q.normal).applyQuaternion(rotation)
      for (const p of fixed) {
        const from = new THREE.Vector3(...p.position), separation = point.clone().sub(from), distance = separation.length()
        if (distance < 0.3 || distance > reach || normal.dot(new THREE.Vector3(...p.normal)) > -0.25) continue
        separation.divideScalar(distance)
        if (separation.dot(new THREE.Vector3(...p.normal)) < 0.15 || separation.dot(normal) > -0.15) continue
        pairs.push({ p, q, from, point, distance })
      }
    }
    pairs.sort((a,b) => a.distance - b.distance || a.p.id.localeCompare(b.p.id) || a.q.id.localeCompare(b.q.id))
    const used = new Set()
    for (const pair of pairs) {
      if (used.has(pair.p.id) || used.has(pair.q.id)) continue
      used.add(pair.p.id); used.add(pair.q.id)
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([pair.from, pair.point]),
        new THREE.LineDashedMaterial({ color: 0x9faec4, dashSize: 0.35, gapSize: 0.2, depthTest: false }))
      line.computeLineDistances(); line.renderOrder = 1000; hints.add(line)
    }
    return hints.children.length
  }
  // Ray-to-axis picking allows clicking anywhere on the body, not just ports.
  function pickCluster(event) {
    const rect = canvas.getBoundingClientRect(), camera = getCamera()
    const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2(2*(event.clientX-rect.left)/rect.width-1, 1-2*(event.clientY-rect.top)/rect.height), camera)
    let best = null
    for (const c of getClusters().filter(c => c.eligible)) for (const id of c.helix_ids ?? []) {
      const axis = getAxes()[id], points = axis?.samples?.length > 1 ? axis.samples : axis ? [axis.start, axis.end] : []
      for (let i = 1; i < points.length; i++) {
        const hit = new THREE.Vector3()
        const distance = ray.ray.distanceSqToSegment(new THREE.Vector3(...points[i-1]), new THREE.Vector3(...points[i]), hit)
        const depth = hit.distanceTo(camera.position)
        if (distance < 2.25 && (!best || depth < best.depth)) best = { id: c.cluster_id, depth }
      }
    }
    return best?.id ?? null
  }
  return {
    attach, detach, showHints, pickCluster,
    clearHints: () => clear(hints),
    setEnabled(value) { if (tc) tc.enabled = value && !!cluster; if (!value) releaseOrbit() },
    setMode(value) { if (!['translate', 'rotate'].includes(value)) return; mode = value; tc?.setMode(value) },
    getMode: () => mode,
    syncCamera() { if (tc) tc.camera = getCamera() },
    ownsPointer: () => !!tc?.axis || !!tc?.dragging,
    setPose(value) {
      if (!cluster || !value.world_translation?.every(Number.isFinite) || !value.world_rotation?.every(Number.isFinite)) return false
      const q = new THREE.Quaternion(...value.world_rotation).normalize(), t = new THREE.Vector3(...value.world_translation)
      target.quaternion.copy(q); target.position.copy(center).applyQuaternion(q).add(t)
      pose = { world_translation: t.toArray(), world_rotation: q.toArray() }
      ghost.position.copy(t); ghost.quaternion.copy(q); onChange(pose); return true
    },
    dispose() { detach(); tc?.dispose(); helper?.removeFromParent(); root.removeFromParent() },
  }
}
