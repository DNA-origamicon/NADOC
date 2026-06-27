// Pure ssDNA flexible-segment PBD relax solver — THREE-free, array-based.
//
// This is the extracted, unit-testable form of the constraint solver that lives
// (today, inline + THREE-coupled) in cluster_gizmo.js `_projectSsdnaConstraints`
// / `_maxSsViolation` / `relaxSsdna`. The math here is a line-for-line
// translation of those functions (cluster_gizmo.js ~808-957), so the headless
// Python port (backend/core/flexible_relax.py) can be pinned for JS↔Python
// parity against this module's golden (see flexible_relax_solver.test.js).
//
// State is plain arrays: pos=[x,y,z] (world position of pivot+translation),
// quat=[x,y,z,w] (THREE convention), pivot=[x,y,z]. A tether is
// {pM0:[x,y,z], pF:[x,y,z], contour:number} — moving-anchor start world pos,
// fixed-anchor world pos, contour length (nm).
//
// Three-Layer note: this only computes a rigid pose; it never touches topology.

const _GAIN = 0.6
const _ITERS = 6
const _OUTER = 80
const _EPS = 1e-3

// ── minimal vec / quat helpers (THREE Vector3 / Quaternion semantics) ──────────
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s]
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const len = (a) => Math.sqrt(dot(a, a))
const dist = (a, b) => len(sub(a, b))
const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
]

function quatFromAxisAngle(axis, angle) {
  const h = angle / 2
  const s = Math.sin(h)
  return [axis[0] * s, axis[1] * s, axis[2] * s, Math.cos(h)]
}

// Hamilton product a⊗b (THREE Quaternion.multiplyQuaternions(a, b)).
function quatMul(a, b) {
  const [ax, ay, az, aw] = a
  const [bx, by, bz, bw] = b
  return [
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  ]
}

const quatInvert = (q) => [-q[0], -q[1], -q[2], q[3]]  // unit quaternion conjugate

// Rotate vector v by quaternion q (THREE Vector3.applyQuaternion).
function applyQuat(q, v) {
  const [qx, qy, qz, qw] = q
  const [vx, vy, vz] = v
  const ix = qw * vx + qy * vz - qz * vy
  const iy = qw * vy + qz * vx - qx * vz
  const iz = qw * vz + qx * vy - qy * vx
  const iw = -qx * vx - qy * vy - qz * vz
  return [
    ix * qw + iw * -qx + iy * -qz - iz * -qy,
    iy * qw + iw * -qy + iz * -qx - ix * -qz,
    iz * qw + iw * -qz + ix * -qy - iy * -qx,
  ]
}

/** Largest amount (nm) any tether exceeds its contour at the candidate pose. */
function maxViolation(candidate, armed) {
  let m = 0
  for (const t of armed) {
    const d = dist(candidate(t.pM0), t.pF) - t.contour
    if (d > m) m = d
  }
  return m
}

/**
 * Relax a single moving cluster's pose to convergence (port of relaxSsdna +
 * _projectSsdnaConstraints).
 * @param {{pos:number[], quat:number[], pivot:number[]}} state mutated in place
 * @param {Array<{pM0:number[], pF:number[], contour:number}>} armed
 * @param {{translateOnly?:boolean, gain?:number, iters?:number, outer?:number, eps?:number}} opts
 * @returns {{moved:boolean, residual:number, pos:number[], quat:number[]}}
 */
export function relaxToConvergence(state, armed, opts = {}) {
  const { translateOnly = false, gain = _GAIN, iters = _ITERS, outer = _OUTER, eps = _EPS } = opts
  const startPos = [...state.pos]
  const startQuat = [...state.quat]
  let incrQuat = [0, 0, 0, 1]

  const candidate = (pM0) => add(applyQuat(incrQuat, sub(pM0, startPos)), state.pos)

  if (!armed.length || maxViolation(candidate, armed) <= eps) {
    return { moved: false, residual: maxViolation(candidate, armed), pos: state.pos, quat: state.quat }
  }

  for (let k = 0; k < outer && maxViolation(candidate, armed) > eps; k++) {
    for (let it = 0; it < iters; it++) {
      // Rotation pass: accumulate torque about the pivot from violations.
      let torque = [0, 0, 0]
      let sumR2 = 0
      let nViol = 0
      for (const t of armed) {
        const pM = candidate(t.pM0)
        const d = dist(pM, t.pF)
        if (d <= t.contour || d < 1e-9) continue
        const target = add(t.pF, mul(sub(pM, t.pF), t.contour / d))
        const delta = sub(target, pM)
        const r = sub(pM, state.pivot)
        torque = add(torque, cross(r, delta))
        sumR2 += dot(r, r)
        nViol++
      }
      if (nViol === 0) break
      if (!translateOnly && sumR2 > 1e-6) {
        const rv = mul(torque, gain / sumR2)
        let angle = len(rv)
        if (angle > 1e-9) {
          if (angle > 0.25) angle = 0.25
          const axis = mul(rv, 1 / len(rv))
          const q = quatFromAxisAngle(axis, angle)
          state.pos = add(applyQuat(q, sub(state.pos, state.pivot)), state.pivot)
          state.quat = quatMul(q, state.quat)            // premultiply
          incrQuat = quatMul(state.quat, quatInvert(startQuat))
        }
      }
      // Translation pass: residual after rotation.
      let dT = [0, 0, 0]
      let nT = 0
      for (const t of armed) {
        const pM = candidate(t.pM0)
        const d = dist(pM, t.pF)
        if (d <= t.contour || d < 1e-9) continue
        const target = add(t.pF, mul(sub(pM, t.pF), t.contour / d))
        dT = add(dT, sub(target, pM))
        nT++
      }
      if (nT > 0) state.pos = add(state.pos, mul(dT, gain / nT))
    }
  }

  return { moved: true, residual: maxViolation(candidate, armed), pos: state.pos, quat: state.quat }
}

export const _internals = { quatMul, applyQuat, quatFromAxisAngle, maxViolation }
