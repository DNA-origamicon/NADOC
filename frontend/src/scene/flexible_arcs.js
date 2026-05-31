/**
 * Flexible ssDNA segment arcs.
 *
 * Draws each `design.flexible_connections` entry as a fixed-contour-length arc
 * between the two rigid cluster anchors. The marked ssDNA beads (excluded from
 * the rigid bead meshes in helix_renderer) are placed along this arc. The arc
 * conserves contour length: it bows more as the chord shortens and straightens
 * toward a line when the chord approaches the contour length ("free until
 * taut"). Pure visualisation — display layer only.
 *
 * Bow DIRECTION is chosen to point AWAY from the nearby helix-bundle cylinders
 * (repulsion from helix-axis centerlines), so a slack arc bulges outward rather
 * than diving through the structure. Recomputed live during a cluster drag (the
 * moving cluster's axes are transformed by the live drag transform), with
 * smoothing/hysteresis to avoid the bow flipping jarringly mid-drag.
 *
 *   const arcs = initFlexibleArcs(scene, designRenderer, () => store.currentHelixAxes)
 *   arcs.rebuild(design)
 *   arcs.applyLiveUpdate(helixIds, centerVec, dummyPos, incrQuat)   // per drag frame
 */
import * as THREE from 'three'

const ARC_COLOR = 0xff33cc      // magenta — flexible ssDNA
const BEAD_RADIUS = 0.12
const TUBE_RADIUS = 0.06
const TUBE_SEGS = 32
const OBST_RADIUS = 12.0        // nm — only cylinders within this of the arc midpoint repel
const BOW_SMOOTH = 0.6          // hysteresis: keep this fraction of the previous bow
const Y_HAT = new THREE.Vector3(0, 1, 0)
const X_HAT = new THREE.Vector3(1, 0, 0)
const GEO_BEAD = new THREE.SphereGeometry(BEAD_RADIUS, 8, 6)
// Base slabs — dims + offset copied from helix_renderer.js slabParams so the
// flexible arc keeps the ball-and-slab look. Box local axes: x=length (0.30),
// y=width (0.06), z=thickness (0.70).
const GEO_SLAB = new THREE.BoxGeometry(0.30, 0.06, 0.70)
const SLAB_DISTANCE = 0.55      // nm — slab centre offset from the bead along the inward base-normal

function _fallbackBow(dHat) {
  let b = new THREE.Vector3().crossVectors(dHat, Y_HAT)
  if (b.lengthSq() < 1e-6) b = new THREE.Vector3().crossVectors(dHat, X_HAT)
  return b.normalize()
}

/** Slab orientation, matching helix_renderer.js slabQuaternion: local x →
 *  tangential, y → tangent (stacking axis), z → base-normal (inward). */
function _slabQuaternion(bnDir, tanDir, out) {
  const tangential = new THREE.Vector3().crossVectors(tanDir, bnDir).normalize()
  const m = new THREE.Matrix4().makeBasis(tangential, tanDir, bnDir)
  return out.setFromRotationMatrix(m)
}

/** Closest point on segment [p0,p1] to point p. */
function _closestOnSeg(p, p0, p1, out) {
  const ab = new THREE.Vector3().subVectors(p1, p0)
  const t = THREE.MathUtils.clamp(new THREE.Vector3().subVectors(p, p0).dot(ab) / (ab.lengthSq() || 1), 0, 1)
  return out.copy(p0).addScaledVector(ab, t)
}

/** n interior points along a circular arc of arc-length `L` from a to b, bowing
 *  toward unit `bowDir` (perpendicular to the chord). */
function _arcPoints(a, b, L, n, bowDir) {
  const pts = []
  if (n <= 0) return pts
  const d = new THREE.Vector3().subVectors(b, a)
  const c = d.length()
  if (c < 1e-6 || c >= L) {                 // taut / coincident → straight
    for (let i = 1; i <= n; i++) pts.push(new THREE.Vector3().lerpVectors(a, b, i / (n + 1)))
    return pts
  }
  // Solve θ ∈ (0,π): sin(θ)/θ = chord/contour. (Half-angle of the circular arc.)
  const ratio = c / L
  let lo = 1e-4, hi = Math.PI - 1e-4
  for (let it = 0; it < 40; it++) {
    const mid = (lo + hi) / 2
    if (Math.sin(mid) / mid > ratio) lo = mid
    else hi = mid
  }
  const theta = (lo + hi) / 2
  const R = L / (2 * theta)
  const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5)
  const O = mid.clone().addScaledVector(bowDir, -R * Math.cos(theta))   // arc centre
  const ua = new THREE.Vector3().subVectors(a, O).normalize()
  const ub = new THREE.Vector3().subVectors(b, O).normalize()
  let axis = new THREE.Vector3().crossVectors(ua, ub)
  if (axis.lengthSq() < 1e-9) axis = new THREE.Vector3().crossVectors(d.clone().normalize(), bowDir)
  axis.normalize()
  const ang = Math.acos(THREE.MathUtils.clamp(ua.dot(ub), -1, 1))
  const q = new THREE.Quaternion()
  for (let i = 1; i <= n; i++) {
    q.setFromAxisAngle(axis, ang * (i / (n + 1)))
    pts.push(ua.clone().applyQuaternion(q).multiplyScalar(R).add(O))
  }
  return pts
}

export function initFlexibleArcs(scene, designRenderer, getHelixAxes = () => null) {
  const group = new THREE.Group()
  group.name = 'flexibleArcs'
  scene.add(group)
  let _design = null
  let _visible = true
  const _lastBow = new Map()   // connection id -> THREE.Vector3 (hysteresis)
  const _tubeMat = new THREE.MeshPhongMaterial({ color: ARC_COLOR })
  const _beadMat = new THREE.MeshPhongMaterial({ color: ARC_COLOR })
  const _slabMat = new THREE.MeshPhongMaterial({ color: ARC_COLOR })

  function _entryPosMap() {
    const m = new Map()
    for (const e of (designRenderer.getBackboneEntries?.() ?? [])) {
      const n = e.nuc
      if (n) m.set(`${n.helix_id}:${n.bp_index}:${n.direction}`, e.pos)
    }
    return m
  }

  function _helixResolver(design) {
    const byId = new Map((design.strands ?? []).map(s => [s.id, s]))
    return (anc) => {
      const s = byId.get(anc.strand_id)
      const d = s?.domains?.[anc.domain_index]
      return d ? `${d.helix_id}:${anc.bp_index}:${anc.direction}` : null
    }
  }

  // Build world-space helix-axis obstacle segments. `live` (when dragging) =
  // {helixIds:Set, centerVec, dummyPos, incrQuat} — transforms the moving
  // cluster's axes so obstacles share the arcs' live frame.
  function _obstacleSegments(live) {
    const axes = getHelixAxes() || {}
    const segs = []
    const xf = (p) => {
      const v = new THREE.Vector3(p[0], p[1], p[2])
      if (live) v.sub(live.centerVec).applyQuaternion(live.incrQuat).add(live.dummyPos)
      return v
    }
    for (const [hid, ax] of Object.entries(axes)) {
      if (!ax?.start || !ax?.end) continue
      const moving = live && live.helixIds?.has(hid)
      const p0 = moving ? xf(ax.start) : new THREE.Vector3(...ax.start)
      const p1 = moving ? xf(ax.end)   : new THREE.Vector3(...ax.end)
      segs.push([p0, p1])
    }
    return segs
  }

  function _bowDir(a, b, connId, obstacles) {
    const d = new THREE.Vector3().subVectors(b, a)
    const dHat = d.clone().normalize()
    const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5)
    // Repulsion from nearby cylinder centerlines.
    const rep = new THREE.Vector3()
    const cp = new THREE.Vector3()
    for (const [p0, p1] of obstacles) {
      _closestOnSeg(mid, p0, p1, cp)
      const v = new THREE.Vector3().subVectors(mid, cp)
      const dist = v.length()
      if (dist < 1e-3 || dist > OBST_RADIUS) continue
      rep.addScaledVector(v.multiplyScalar(1 / dist), 1 / (dist * dist))   // unit·(1/d²)
    }
    // Project onto the plane perpendicular to the chord.
    rep.addScaledVector(dHat, -rep.dot(dHat))
    let bow = (rep.lengthSq() > 1e-9) ? rep.normalize() : (_lastBow.get(connId)?.clone() ?? _fallbackBow(dHat))
    // Hysteresis: blend with the previous bow, then re-project + renormalise.
    const last = _lastBow.get(connId)
    if (last) {
      bow = last.clone().multiplyScalar(BOW_SMOOTH).addScaledVector(bow, 1 - BOW_SMOOTH)
      bow.addScaledVector(dHat, -bow.dot(dHat))
      if (bow.lengthSq() < 1e-9) bow = _fallbackBow(dHat)
      bow.normalize()
    }
    _lastBow.set(connId, bow.clone())
    return bow
  }

  function _clear() {
    for (const ch of [...group.children]) {
      group.remove(ch)
      ch.geometry?.dispose?.()
    }
  }

  function _drawArc(pA, pB, beads, bow, connId) {
    const pts = [pA, ...beads, pB]
    const curve = new THREE.CatmullRomCurve3(pts)
    const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, TUBE_SEGS, TUBE_RADIUS, 6, false), _tubeMat)
    tube.userData.connectionId = connId
    group.add(tube)
    if (!beads.length) return
    const inst = new THREE.InstancedMesh(GEO_BEAD, _beadMat, beads.length)
    const m = new THREE.Matrix4()
    beads.forEach((p, i) => { m.makeTranslation(p.x, p.y, p.z); inst.setMatrixAt(i, m) })
    inst.instanceMatrix.needsUpdate = true
    inst.frustumCulled = false
    inst.userData.connectionId = connId
    group.add(inst)
    // Base slabs — base-normal faces inward toward the arc's centre of
    // curvature (same orientation curved dsDNA uses). The arc is planar with
    // plane normal `planeN`; the in-plane normal ⟂ tangent, flipped to oppose
    // the (outward) bow, points at the centre.
    const planeN = new THREE.Vector3().crossVectors(
      new THREE.Vector3().subVectors(pB, pA).normalize(), bow)
    if (planeN.lengthSq() < 1e-9) return
    planeN.normalize()
    const slabs = new THREE.InstancedMesh(GEO_SLAB, _slabMat, beads.length)
    const sm = new THREE.Matrix4(), q = new THREE.Quaternion()
    const tan = new THREE.Vector3(), bn = new THREE.Vector3(), center = new THREE.Vector3()
    const scl = new THREE.Vector3(1, 1, 1)
    for (let i = 0; i < beads.length; i++) {
      tan.subVectors(pts[i + 2], pts[i]).normalize()      // arc tangent (stacking axis)
      bn.crossVectors(planeN, tan).normalize()            // in-plane, ⟂ tangent
      if (bn.dot(bow) > 0) bn.negate()                    // face the centre of curvature
      center.copy(beads[i]).addScaledVector(bn, SLAB_DISTANCE)
      _slabQuaternion(bn, tan, q)
      sm.compose(center, q, scl)
      slabs.setMatrixAt(i, sm)
    }
    slabs.instanceMatrix.needsUpdate = true
    slabs.frustumCulled = false
    slabs.userData.connectionId = connId
    group.add(slabs)
  }

  const _ray = new THREE.Raycaster()
  const _ndc = new THREE.Vector2()
  /** Raycast the flexible arcs; return the hit connection id, or null. */
  function hitTest(clientX, clientY, camera, canvas) {
    if (!_visible || !group.children.length) return null
    const rect = canvas.getBoundingClientRect()
    _ndc.set(((clientX - rect.left) / rect.width) * 2 - 1,
             -((clientY - rect.top) / rect.height) * 2 + 1)
    _ray.setFromCamera(_ndc, camera)
    const hits = _ray.intersectObjects(group.children, false)
    return hits.length ? (hits[0].object.userData.connectionId ?? null) : null
  }

  function _render(live = null) {
    _clear()
    if (!_design || !_visible) return
    const conns = _design.flexible_connections ?? []
    if (!conns.length) return
    const posMap = _entryPosMap()
    const helixOf = _helixResolver(_design)
    const obstacles = _obstacleSegments(live)
    for (const c of conns) {
      const pA = posMap.get(helixOf(c.anchor_a) ?? '')
      const pB = posMap.get(helixOf(c.anchor_b) ?? '')
      if (!pA || !pB) continue
      const bow = _bowDir(pA, pB, c.id, obstacles)
      _drawArc(pA, pB, _arcPoints(pA, pB, c.contour_length_nm, c.n_ss_bases, bow), bow, c.id)
    }
  }

  function rebuild(design) { _design = design; if (!design?.flexible_connections?.length) _lastBow.clear(); _render(null) }
  function applyLiveUpdate(helixIds, centerVec, dummyPos, incrQuat) {
    const live = (helixIds && centerVec && dummyPos && incrQuat)
      ? { helixIds: new Set(helixIds), centerVec, dummyPos, incrQuat }
      : null
    _render(live)
  }
  function setVisible(v) { _visible = v; group.visible = v; if (v) _render(); else _clear() }
  function dispose() {
    _clear(); scene.remove(group); _tubeMat.dispose(); _beadMat.dispose(); _slabMat.dispose()
    GEO_BEAD.dispose(); GEO_SLAB.dispose()
  }

  return { rebuild, applyLiveUpdate, setVisible, dispose, hitTest, group }
}
