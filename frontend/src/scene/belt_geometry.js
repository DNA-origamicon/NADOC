/**
 * Belt geometry — pure (display-only) math for the open belt-path preview.
 *
 * A pulley is a revolute joint (axis) plus a rim connector. The pulley CENTER is
 * the closest point on the axis line to the connector; the RADIUS is the
 * perpendicular distance from the connector to that axis line (invariant under
 * rotation about the axis).
 *
 * For two pulleys we build an OPEN belt: the two EXTERNAL tangent lines plus the
 * wrap arcs on each pulley (larger pulley wraps > 180°, smaller < 180°). Both
 * pulleys spin the same sense.
 *
 * THREE-LAYER LAW: this is display-layer geometry only. Nothing here mutates any
 * Design or assembly topology.
 */
import * as THREE from 'three'

const _v = (a) => new THREE.Vector3(a[0], a[1], a[2])

/**
 * Express every BeltPath as a GearRelation-shaped coupling edge so the kinematics
 * ticker + live-drag can drive belts with the same machinery as gears.
 *
 * An open belt couples its two pulley joints at angular ratio r_a/r_b (equal rim
 * speed) in the SAME world rotational sense. The current_value→physical-rotation
 * map per pulley is +1 for the child side ('b') and −1 for the parent side ('a');
 * the world sense also flips when the joint axes point opposite ways. So
 * invert = (s_a · s_b · sign(axis_a · axis_b)) < 0. Mirrors backend
 * `_belt_to_relation`. Returns objects shaped like a GearRelation.
 */
export function beltCouplingRelations(assembly) {
  const joints = assembly?.joints ?? []
  const byId = new Map(joints.map(j => [j.id, j]))
  const out = []
  for (const belt of (assembly?.belt_paths ?? [])) {
    const ja = byId.get(belt.pulley_a?.joint_id)
    const jb = byId.get(belt.pulley_b?.joint_id)
    if (!ja || !jb) continue
    const rA = belt.pulley_a.radius, rB = belt.pulley_b.radius
    if (!(rA > 1e-6) || !(rB > 1e-6)) continue
    const sA = belt.pulley_a.side === 'a' ? -1 : 1
    const sB = belt.pulley_b.side === 'a' ? -1 : 1
    const dA = ja.axis_direction ?? [0, 0, 1]
    const dB = jb.axis_direction ?? [0, 0, 1]
    const dot = dA[0] * dB[0] + dA[1] * dB[1] + dA[2] * dB[2]
    const invert = (sA * sB * (dot >= 0 ? 1 : -1)) < 0
    out.push({
      id: `__belt__${belt.id}`,
      joint_a_id: belt.pulley_a.joint_id,
      joint_b_id: belt.pulley_b.joint_id,
      ratio: rA / rB,
      invert,
      joint_a_anchor: belt.joint_a_anchor ?? 0,
      joint_b_anchor: belt.joint_b_anchor ?? 0,
      endpoint_a_instance_id: belt.pulley_a.instance_id,
      endpoint_b_instance_id: belt.pulley_b.instance_id,
      endpoint_a_side: belt.pulley_a.side,
      endpoint_b_side: belt.pulley_b.side,
    })
  }
  return out
}

/**
 * Pulley center (closest point on the axis line to the connector) + radius.
 * @param {number[]} axisOrigin  point on the revolute axis (world)
 * @param {number[]} axisDir     axis direction (world; need not be unit)
 * @param {number[]} connector   rim connector world position
 * @returns {{center: THREE.Vector3, radius: number}}
 */
export function pulleyCenterRadius(axisOrigin, axisDir, connector) {
  const O = _v(axisOrigin)
  const a = _v(axisDir)
  if (a.lengthSq() < 1e-12) return { center: O.clone(), radius: 0 }
  a.normalize()
  const P = _v(connector)
  const t = P.clone().sub(O).dot(a)
  const center = O.clone().addScaledVector(a, t)
  const radius = P.clone().sub(center).length()
  return { center, radius }
}

/** Total arc length of the closed belt polyline. */
export function beltLoopLength(points) {
  let L = 0
  for (let i = 0; i < points.length; i++) L += points[i].distanceTo(points[(i + 1) % points.length])
  return L
}

/**
 * SE(3) belt frame at arc-length parameter `arcParam` (0..1, wraps): position =
 * point on the loop; x-axis = travel tangent; z-axis = belt plane normal; y = z×x.
 * @returns {THREE.Matrix4}
 */
export function beltFrameAt(points, arcParam, planeNormal) {
  const L = beltLoopLength(points)
  const target = (((arcParam % 1) + 1) % 1) * L
  let acc = 0
  const n = _v(planeNormal).normalize()
  for (let i = 0; i < points.length; i++) {
    const a = points[i], b = points[(i + 1) % points.length]
    const seg = a.distanceTo(b)
    if (acc + seg >= target || i === points.length - 1) {
      const t = seg > 1e-9 ? (target - acc) / seg : 0
      const point = a.clone().lerp(b, t)
      const x = b.clone().sub(a).normalize()
      const y = new THREE.Vector3().crossVectors(n, x).normalize()
      const z = new THREE.Vector3().crossVectors(x, y)
      const M = new THREE.Matrix4().makeBasis(x, y, z)
      M.setPosition(point)
      return M
    }
    acc += seg
  }
  return new THREE.Matrix4().setPosition(points[0])
}

/**
 * ds/d(current_value_a) — how far (signed arc length, in polyline-order
 * direction) the belt advances per radian of pulley-A's joint value. The belt
 * must travel WITH the pulley rim. Pulley A's body physically rotates by
 * s_a · current_value about its axis (s_a = +1 if the moving body is the joint's
 * child side 'b', −1 if the parent side 'a'), so the rim velocity per unit
 * current_value is s_a·(axis_a × r_vec); dotting with the loop tangent at an
 * on-arc point gives the signed scale (≈ ±r_a). The s_a factor is why a hardcoded
 * sign breaks when a belt is recreated on the other endpoint side.
 */
export function beltDriveScale(belt, jointById, points) {
  const ja = jointById.get(belt.pulley_a?.joint_id)
  if (!ja) return 0
  const center = _v(belt.pulley_a.center_world)
  const axis = _v(ja.axis_direction).normalize()
  const rA = belt.pulley_a.radius
  const sA = belt.pulley_a.side === 'a' ? -1 : 1
  const tol = 1e-3 * rA + 1e-4
  const onCircle = (p) => Math.abs(p.distanceTo(center) - rA) < tol
  // Collect run of consecutive arc-A points; pick the middle (interior) one.
  const idxs = []
  for (let i = 0; i < points.length; i++) {
    if (onCircle(points[i]) && onCircle(points[(i + 1) % points.length])) idxs.push(i)
  }
  if (!idxs.length) return rA * sA
  const i = idxs[Math.floor(idxs.length / 2)]
  const rvec = points[i].clone().sub(center)
  const tangent = points[(i + 1) % points.length].clone().sub(points[i]).normalize()
  return sA * new THREE.Vector3().crossVectors(axis, rvec).dot(tangent)
}

/** Live arc-length parameter (0..1, may exceed via mod in beltFrameAt) of a rider. */
export function riderLiveArc(belt, jointById, rider, thetaA, points) {
  const L = beltLoopLength(points)
  if (L < 1e-9) return rider.arc_param ?? 0
  const scale = beltDriveScale(belt, jointById, points)
  return (rider.arc_param ?? 0) + (thetaA - (rider.ref_angle ?? 0)) * scale / L
}

/**
 * Drive every belt rider to its live pose for the current pulley angles.
 * @param {object} assembly
 * @param {(jointId, joint) => number} thetaOf  current pulley-A angle source
 * @param {(instanceId, THREE.Matrix4) => void} applyMat
 */
export function applyBeltRiders(assembly, thetaOf, applyMat) {
  const riders = assembly?.belt_riders ?? []
  if (!riders.length) return
  const jointById = new Map((assembly.joints ?? []).map(j => [j.id, j]))
  const beltById = new Map((assembly.belt_paths ?? []).map(b => [b.id, b]))
  const pointsCache = new Map()
  for (const rider of riders) {
    const belt = beltById.get(rider.belt_path_id)
    const ja = belt ? jointById.get(belt.pulley_a?.joint_id) : null
    if (!belt || !ja || !rider.local_transform) continue
    if (!pointsCache.has(belt.id)) pointsCache.set(belt.id, beltCurvePoints(belt, jointById))
    const points = pointsCache.get(belt.id)
    if (!points) continue
    const thetaA = thetaOf(belt.pulley_a.joint_id, ja)
    const arc = riderLiveArc(belt, jointById, rider, thetaA, points)
    const F = beltFrameAt(points, arc, ja.axis_direction)
    const local = new THREE.Matrix4().fromArray(rider.local_transform).transpose()
    applyMat(rider.instance_id, F.multiply(local))
  }
}

/**
 * Seating transform for attaching a part to the belt: the new world transform
 * that moves the part so its connector lands on `beltPoint` with the connector
 * normal aligned to the belt `tangent` (travel direction). `planeNormal` (the
 * belt plane normal) is the "up" that pins the remaining roll DOF.
 *
 * @returns {THREE.Matrix4} new instance world transform (= D · instMat)
 */
export function seatTransform(connWorldPos, connWorldNorm, beltPoint, tangent, planeNormal, instMat) {
  const Pc = connWorldPos.clone()
  const buildBasis = (axisV, upV) => {
    const e1 = axisV.clone().normalize()
    let e2 = upV.clone().addScaledVector(e1, -upV.dot(e1))
    if (e2.lengthSq() < 1e-9) {
      e2 = (Math.abs(e1.x) < 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0))
      e2.addScaledVector(e1, -e2.dot(e1))
    }
    e2.normalize()
    const e3 = new THREE.Vector3().crossVectors(e1, e2)
    return new THREE.Matrix4().makeBasis(e1, e2, e3)
  }
  // R aligns the connector normal → belt tangent, with planeNormal as up.
  const R = buildBasis(tangent, planeNormal).multiply(buildBasis(connWorldNorm, planeNormal).invert())
  const D = new THREE.Matrix4()
    .makeTranslation(beltPoint.x, beltPoint.y, beltPoint.z)
    .multiply(R)
    .multiply(new THREE.Matrix4().makeTranslation(-Pc.x, -Pc.y, -Pc.z))
  return D.multiply(instMat)
}

/**
 * Belt polyline (closed loop of Vec3) from a stored BeltPath's cached geometry,
 * or null if it can't be built. `jointById` maps joint id → joint (for axes).
 */
export function beltCurvePoints(belt, jointById) {
  const ja = jointById.get(belt.pulley_a?.joint_id)
  const jb = jointById.get(belt.pulley_b?.joint_id)
  if (!ja || !jb || !belt.pulley_a?.center_world || !belt.pulley_b?.center_world) return null
  const res = computeBeltPath(
    { center: _v(belt.pulley_a.center_world), radius: belt.pulley_a.radius, axisDir: ja.axis_direction },
    { center: _v(belt.pulley_b.center_world), radius: belt.pulley_b.radius, axisDir: jb.axis_direction },
  )
  return res.error ? null : res.points
}

/**
 * Closest point on the closed belt polyline to a world point.
 * @returns {{ arcParam: number, point: THREE.Vector3, tangent: THREE.Vector3 }}
 *   arcParam is 0..1 by arc length; tangent is the loop travel direction there.
 */
export function nearestArcParam(points, worldPoint) {
  const n = points.length
  let bestD = Infinity, bestSeg = 0, bestT = 0
  const segLens = []
  let total = 0
  for (let i = 0; i < n; i++) {
    const a = points[i], b = points[(i + 1) % n]
    const len = a.distanceTo(b)
    segLens.push(len); total += len
    const ab = b.clone().sub(a)
    const len2 = ab.lengthSq()
    let t = len2 > 1e-12 ? worldPoint.clone().sub(a).dot(ab) / len2 : 0
    t = Math.max(0, Math.min(1, t))
    const d = a.clone().addScaledVector(ab, t).distanceToSquared(worldPoint)
    if (d < bestD) { bestD = d; bestSeg = i; bestT = t }
  }
  let cum = 0
  for (let i = 0; i < bestSeg; i++) cum += segLens[i]
  cum += bestT * segLens[bestSeg]
  const a = points[bestSeg], b = points[(bestSeg + 1) % n]
  return {
    arcParam: total > 0 ? cum / total : 0,
    point: a.clone().lerp(b, bestT),
    tangent: b.clone().sub(a).normalize(),
  }
}

/**
 * Build the open-belt polyline wrapping two pulleys.
 *
 * @param {object} A  pulley A: { center: Vector3, radius, axisDir: number[] }
 * @param {object} B  pulley B: { center: Vector3, radius, axisDir: number[] }
 * @returns {{points: THREE.Vector3[], rA, rB, distance, warning} | {error}}
 *   `points` is a closed loop ready for a CatmullRomCurve3(points, true).
 *   On a degenerate configuration returns `{ error: <reason> }`.
 */
export function computeBeltPath(A, B) {
  const rA = A.radius
  const rB = B.radius
  if (!(rA > 1e-6) || !(rB > 1e-6)) return { error: 'Pulley radius is ~zero — pick a rim connector off the axis.' }

  // Plane normal = pulley A's axis. Project B's center into A's belt plane.
  const n = _v(A.axisDir)
  if (n.lengthSq() < 1e-12) return { error: 'Pulley A axis is degenerate.' }
  n.normalize()

  const nB = _v(B.axisDir)
  let warning = null
  if (nB.lengthSq() > 1e-12) {
    nB.normalize()
    if (Math.abs(nB.dot(n)) < Math.cos((5 * Math.PI) / 180)) {
      warning = 'Pulley axes are not parallel — belt preview is approximate.'
    }
  }

  const cA = A.center.clone()
  const cBraw = B.center.clone()
  // Drop the out-of-plane component of (cB - cA) so both centers are coplanar.
  const dCB = cBraw.clone().sub(cA)
  const cB = cBraw.clone().addScaledVector(n, -dCB.dot(n))

  const u = cB.clone().sub(cA)
  const D = u.length()
  if (D < 1e-6) return { error: 'Pulleys are concentric — no belt path.' }
  u.multiplyScalar(1 / D)
  const v = n.clone().cross(u)
  if (v.lengthSq() < 1e-12) return { error: 'Cannot build belt plane basis.' }
  v.normalize()

  if (D < Math.abs(rA - rB)) {
    return { error: 'One pulley is nested inside the other — no external belt.' }
  }

  // External-tangent contact angle (from the A→B axis, in the (u,v) plane):
  //   psi = acos((rA - rB) / D)
  // Tangent contact normals: nUp at +psi, nLo at -psi (same direction on both
  // circles). Larger pulley wraps the major arc; smaller the minor arc.
  const psi = Math.acos(Math.max(-1, Math.min(1, (rA - rB) / D)))

  // 3D point at contact angle `t` on a circle of radius `r` centred at `c`.
  const ptOn = (c, r, t) =>
    c.clone().addScaledVector(u, r * Math.cos(t)).addScaledVector(v, r * Math.sin(t))

  const points = []
  const ARC_STEP = Math.PI / 32 // ~5.6°
  const sampleArc = (c, r, a0, a1) => {
    const span = a1 - a0
    const steps = Math.max(2, Math.round(Math.abs(span) / ARC_STEP))
    for (let k = 0; k <= steps; k++) points.push(ptOn(c, r, a0 + (span * k) / steps))
  }
  const sampleSeg = (p0, p1, steps = 4) => {
    // interior points only (endpoints come from the adjacent arcs)
    for (let k = 1; k < steps; k++) points.push(p0.clone().lerp(p1, k / steps))
  }

  // Arc B: +psi → -psi through 0 (far side of B, away from A) → minor for smaller B.
  sampleArc(cB, rB, psi, -psi)
  const T_B_lo = ptOn(cB, rB, -psi)
  const T_A_lo = ptOn(cA, rA, -psi)
  // Lower tangent B → A.
  sampleSeg(T_B_lo, T_A_lo)
  // Arc A: -psi → +psi the long way through ±pi (back side of A, away from B).
  sampleArc(cA, rA, -psi, -(2 * Math.PI - psi))
  const T_A_up = ptOn(cA, rA, psi)
  const T_B_up = ptOn(cB, rB, psi)
  // Upper tangent A → B (closes the loop back to the first arc-B point).
  sampleSeg(T_A_up, T_B_up)

  return { points, rA, rB, distance: D, warning }
}
