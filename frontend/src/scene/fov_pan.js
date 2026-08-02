/**
 * FOV-normalised pan scaling.
 *
 * TrackballControls-derived modes (Trackball and Multiscale, which is built on
 * it) scale pan by `|camera − target|` alone — `panCamera()` multiplies the
 * mouse delta by `_eye.length() * panSpeed`, with no lens term. The WASD nav
 * controller does the same thing with its own `dist * SPEED_FRAC`.
 *
 * That is correct only at a fixed lens. Photo mode's FOV slider DOLLIES the
 * camera to preserve framing (`dollyDistanceForFov`: distance ∝ 1/tan(fov/2)),
 * so at 8° the camera sits ~7× further from the pivot than at 55° and pan runs
 * ~7× too fast, while at 90° it barely moves.
 *
 * What actually sets on-screen pan speed is the world height of the frustum at
 * the pivot, `distance * tan(fov/2)` — the same quantity `dollyDistanceForFov`
 * holds constant. Multiplying a distance-based speed by tan(fov/2)/tan(ref/2)
 * restores it. The factor is exactly 1 at the default 55° lens, so ordinary
 * editing feel outside photo mode is untouched.
 */

const DEG2RAD = Math.PI / 180

/** The camera's construction FOV in `scene.js` — the lens all pan tuning
 *  constants (panSpeed, SPEED_FRAC) were dialled in at. */
export const PAN_REF_FOV = 55

/**
 * Multiplier that turns a distance-proportional pan speed into a
 * framing-proportional one.
 *
 * @param {number} fovDeg     — the camera's current vertical FOV (degrees)
 * @param {number} [refFovDeg]— the lens the speed constants were tuned at
 * @returns {number} tan(fov/2) / tan(ref/2); 1 for a bad or reference FOV
 */
export function fovPanScale(fovDeg, refFovDeg = PAN_REF_FOV) {
  // tan(90°) is merely huge rather than Infinity in floating point, so bound
  // the angles first — a garbage FOV must not multiply pan by 1e16.
  if (!_usableFov(fovDeg) || !_usableFov(refFovDeg)) return 1
  const f = Math.tan((fovDeg * DEG2RAD) / 2)
  const r = Math.tan((refFovDeg * DEG2RAD) / 2)
  if (f <= 0 || r <= 0) return 1
  return f / r
}

function _usableFov(deg) { return Number.isFinite(deg) && deg > 0 && deg < 179 }
