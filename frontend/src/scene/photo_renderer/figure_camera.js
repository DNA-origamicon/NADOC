/**
 * Photo mode — near-parallel ("long lens") projection maths.
 *
 * Why not a real OrthographicCamera: the whole photo pipeline is wired to the
 * one shared PerspectiveCamera — SSAO/GTAO bake a PERSPECTIVE_CAMERA shader
 * define, the volumetric-inscatter pass marches perspective rays, the path
 * tracer builds its camera from it, OrbitControls' zoom means "distance" on it,
 * and main.js rewrites its near/far every frame. Swapping in an ortho camera
 * means touching every one of those, and the composer cannot be rebuilt after
 * activate (PMREM state → bloom paints garbage; see project_photo_mode.md).
 *
 * A long lens gets the thing that actually matters for a figure — no visible
 * vanishing point, no perspective distortion across the structure — with none
 * of that risk. At 8° the residual convergence over a 60 nm object is well
 * under a pixel at print resolution: visually parallel.
 *
 * To keep the subject the same size on screen when the FOV changes, the camera
 * must dolly along its view axis. That is the only real maths here, and it is
 * pure so it can be tested without a GL context.
 */

const DEG2RAD = Math.PI / 180

/**
 * Camera distance that preserves apparent subject size across a FOV change.
 *
 *   halfHeight = distance * tan(fov / 2)   (constant ⇒ same framing)
 *
 * @param {number} distance    — current distance from camera to orbit target (nm)
 * @param {number} fromFovDeg  — current vertical FOV (degrees)
 * @param {number} toFovDeg    — desired vertical FOV (degrees)
 * @returns {number} the distance to dolly to
 */
export function dollyDistanceForFov(distance, fromFovDeg, toFovDeg) {
  const from = Math.tan((fromFovDeg * DEG2RAD) / 2)
  const to   = Math.tan((toFovDeg   * DEG2RAD) / 2)
  if (!(to > 0) || !(from > 0) || !(distance > 0)) return distance
  return distance * (from / to)
}

/**
 * FOV below which we call the projection "parallel". Also the FOV the Parallel
 * checkbox snaps to. Lower is more parallel but dollies the camera further out
 * (distance scales as 1/tan(fov/2)), which eventually collides with the camera
 * far clip on large assemblies — 8° is the practical floor.
 */
export const PARALLEL_FOV = 8

/** The FOV restored when Parallel is switched back off. */
export const PERSPECTIVE_FOV = 55
