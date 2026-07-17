/**
 * Hard-surface (oxDNA repulsion plane) math — pure, unit-tested.
 *
 * The "Hard surface" sub-section of the oxDNA panel lets the user place an
 * axis-aligned floor (reusing photo-mode's six-axis floor convention) that the
 * relaxed structure can't pass through, plus tether anchors holding it to that
 * surface.  This module holds the geometry/spec helpers; all DOM wiring lives in
 * ui/oxdna_floor_setup.js.
 *
 * Display-layer only: nothing here mutates topology.
 */

// Outward-pointing unit normals for each floor side — identical convention to
// photo-mode's floor (scene/photo_renderer/floor.js AXIS_NORMALS).  The normal
// points from the surface toward the structure (the allowed half-space), which
// is exactly oxDNA's repulsion-plane `dir`.
export const FLOOR_AXIS_NORMALS = {
  '-y': [0, 1, 0],   // floor below, normal points up
  '+y': [0, -1, 0],  // floor above, normal points down
  '-x': [1, 0, 0],   // floor to the left, normal points right
  '+x': [-1, 0, 0],  // floor to the right, normal points left
  '-z': [0, 0, 1],   // floor in front, normal points back
  '+z': [0, 0, -1],  // floor behind, normal points forward
}

/** Unit normal for a floor side, or null for 'off' / unknown. */
export function floorNormal(axis) {
  const n = FLOOR_AXIS_NORMALS[axis]
  return n ? n.slice() : null
}

/** Inverse of floorNormal: the floor side ('-y', '+x', …) whose outward normal
 * best matches `dir` (largest dot product).  Used to re-select the axis dropdown
 * when a stored surface spec is loaded back into the card.  Returns null for a
 * missing/zero vector. */
export function axisForNormal(dir) {
  if (!Array.isArray(dir)) return null
  const len = Math.hypot(_num(dir[0]), _num(dir[1]), _num(dir[2]))
  if (len < 0.5) return null
  let best = null, bestDot = -Infinity
  for (const [axis, n] of Object.entries(FLOOR_AXIS_NORMALS)) {
    const dot = (n[0] * dir[0] + n[1] * dir[1] + n[2] * dir[2]) / len
    if (dot > bestDot) { bestDot = dot; best = axis }
  }
  return best
}

const _num = (x) => (Number.isFinite(Number(x)) ? Number(x) : 0)

/**
 * Assemble the hard-surface spec from the panel inputs.  Returns null when the
 * axis is unknown (nothing to place).  Otherwise:
 *   { dir: [x,y,z] (unit normal), offsetNm, stiff }
 * The absolute plane height is derived backend-side from the structure's extent
 * along `dir` (it works with no anchors — anchors are an independent element);
 * `offsetNm` is the clearance the surface sits beyond the structure's low point.
 */
export function floorSurfaceSpec({ axis, offsetNm, stiff } = {}) {
  const dir = floorNormal(axis)
  if (!dir) return null
  return { dir, offsetNm: _num(offsetNm), stiff: Math.max(0, _num(stiff)) }
}

/** World-axis coordinate where a side first contacts an axis-aligned bounds box. */
export function floorContactCoordinate(axis, bounds) {
  const lo = bounds?.min, hi = bounds?.max
  if (!lo || !hi) return null
  const component = axis?.slice(-1)
  const i = component === 'x' ? 0 : component === 'y' ? 1 : component === 'z' ? 2 : -1
  if (i < 0) return null
  const value = axis[0] === '-' ? lo[i] : hi[i]
  return Number.isFinite(Number(value)) ? Number(value) : null
}

/** Convert an absolute world-axis plane coordinate to backend clearance. */
export function floorClearanceFromAbsolute(axis, positionNm, bounds) {
  const contact = floorContactCoordinate(axis, bounds)
  if (contact == null) return _num(positionNm)
  const sign = axis[0] === '-' ? 1 : -1
  const clearance = sign * (contact - _num(positionNm))
  return Math.abs(clearance) < 1e-12 ? 0 : clearance
}

/** Convert a stored backend clearance back to an absolute world-axis coordinate. */
export function floorAbsoluteFromClearance(axis, clearanceNm, bounds) {
  const contact = floorContactCoordinate(axis, bounds)
  if (contact == null) return _num(clearanceNm)
  const sign = axis[0] === '-' ? 1 : -1
  return contact - sign * _num(clearanceNm)
}

/**
 * Is the surface spec runnable?  Needs a real normal + a positive stiffness.  No
 * anchor requirement — a bare repulsion plane is a valid steric surface (anchors
 * are a separate, independently-addable element).
 */
export function floorSpecReady(spec) {
  if (!spec) return false
  const len = Math.hypot(_num(spec.dir?.[0]), _num(spec.dir?.[1]), _num(spec.dir?.[2]))
  return len > 0.5 && spec.stiff > 0
}

/** Format the offset slider value (signed nm) for the label. */
export function formatOffsetNm(nm) {
  return `${_num(nm).toFixed(1)} nm`
}
