/**
 * Pure math for the "Multiscale" navigation mode — NADOC's default orbit mode
 * (View → Orbit mode → Multiscale).
 *
 * The mode is one rule, applied identically at every scale:
 *
 *     navScale = clamp(distance from the camera to the nearest helix axis, …)
 *     step     = navScale × (1 − (1 − zoomFrac)^notches)   … along the cursor ray
 *
 * Far from the structure, `navScale` *is* the distance to the structure, so one
 * wheel notch covers a fixed fraction of the remaining gap: the zoom step is
 * proportional to distance and decelerates smoothly as you arrive.
 *
 * Close to — or inside — a bundle, `navScale` pins to the local helix spacing
 * (~2.6 nm in the core of a 6hb) and stops changing. The pace therefore becomes
 * *constant*: you can scroll straight down the core of a 374 nm bundle, from one
 * end through to the other and out the far side, at an unchanging speed.
 *
 * That "no stall" property is the whole point. The stock OrbitControls and
 * TrackballControls dolly is relative to the orbit *target*, so its step decays
 * to zero as the camera approaches the target and you can never pass through it.
 * Here nothing is measured against the target, so there is nothing to stall on.
 *
 * All distances are nanometres (NADOC world units).
 */

/** Defaults. Live-tunable at runtime via `window.__NADOC_DBG__.msNav.set()`. */
export const MULTISCALE_DEFAULTS = {
  zoomFrac: 0.35,   // fraction of navScale covered by one un-boosted notch
  minScale: 0.8,    // nm — floor, so the step can never reach zero and stall
  maxScale: 4000,   // nm — cap, so an empty scene can't produce an absurd jump
  boost:    20,     // Shift multiplier on navScale: precise ↔ travel
  minPivot: 1.5,    // nm — closest the orbit pivot may sit in front of the camera
  maxNotch: 4,      // clamp per wheel event (trackpads emit huge deltaY)
}

/**
 * Squared distance from point p to the line *segment* ab. Squared to keep the
 * inner loop of nearestAxisDistance() free of sqrt.
 */
export function distanceToSegmentSq(
  px, py, pz,
  ax, ay, az,
  bx, by, bz,
) {
  const abx = bx - ax, aby = by - ay, abz = bz - az
  const apx = px - ax, apy = py - ay, apz = pz - az

  const abLenSq = abx * abx + aby * aby + abz * abz
  // Degenerate (zero-length) segment → distance to the single point a.
  let t = abLenSq > 0 ? (apx * abx + apy * aby + apz * abz) / abLenSq : 0
  if (t < 0) t = 0
  else if (t > 1) t = 1

  const dx = apx - t * abx
  const dy = apy - t * aby
  const dz = apz - t * abz
  return dx * dx + dy * dy + dz * dz
}

/**
 * Flatten a design's helix axes into a Float64Array of [ax,ay,az, bx,by,bz, …].
 *
 * This reads the *geometric* layer (helix axis endpoints derived from topology)
 * — it never writes it, and the camera never writes back anywhere. A design
 * relaxed into a curved shape will have straight axis segments here, so the
 * nav scale is approximate for heavily bent structures; that is fine, it only
 * sets a navigation speed.
 */
export function axisSegments(design) {
  const helices = design?.helices
  if (!Array.isArray(helices) || helices.length === 0) return new Float64Array(0)

  const out = new Float64Array(helices.length * 6)
  let n = 0
  for (const h of helices) {
    const a = h?.axis_start, b = h?.axis_end
    if (!a || !b) continue
    if (!Number.isFinite(a.x) || !Number.isFinite(b.x)) continue
    out[n++] = a.x; out[n++] = a.y; out[n++] = a.z
    out[n++] = b.x; out[n++] = b.y; out[n++] = b.z
  }
  return n === helices.length * 6 ? out : out.subarray(0, n)
}

/**
 * Memoize axisSegments() on the identity of the design object, so a wheel event
 * doesn't re-flatten every helix. `getDesign` is called on each query; the
 * segments are rebuilt only when it returns a different object (the store
 * replaces `currentDesign` wholesale on every edit, so identity is sufficient).
 */
export function makeSegmentCache(getDesign) {
  let key = null
  let segs = new Float64Array(0)
  return () => {
    const design = getDesign()
    if (design !== key) {
      key = design
      segs = axisSegments(design)
    }
    return segs
  }
}

/**
 * Distance from a point to the nearest helix axis, or Infinity when there are
 * no segments (empty scene). Brute force over every segment — a wheel event
 * costs O(#helices), which is nothing even for a design with thousands.
 */
export function nearestAxisDistance(px, py, pz, segs) {
  let best = Infinity
  for (let i = 0; i + 5 < segs.length; i += 6) {
    const d2 = distanceToSegmentSq(
      px, py, pz,
      segs[i],     segs[i + 1], segs[i + 2],
      segs[i + 3], segs[i + 4], segs[i + 5],
    )
    if (d2 < best) best = d2
  }
  return best === Infinity ? Infinity : Math.sqrt(best)
}

/**
 * The local navigation scale: how big "one unit of travel" is where the camera
 * currently sits. `dist` is the distance to the nearest structure; `fallback` is
 * used when there is none (Infinity / NaN — e.g. an empty workspace).
 *
 * Shift multiplies the *scale*, not the notch count. That gives a clean split:
 * un-boosted is precise work at helix scale, Shift is travel — inside a 6hb the
 * scale jumps ~2.6 nm → ~52 nm, so a bundle you'd otherwise cross in a few
 * hundred notches crosses in a couple of dozen, using the identical rule.
 */
export function navScaleAt(dist, fallback, { minScale, maxScale, boost }, boosted = false) {
  let d = Number.isFinite(dist) ? dist : fallback
  if (!Number.isFinite(d)) d = minScale
  if (d < minScale) d = minScale
  else if (d > maxScale) d = maxScale
  return boosted ? d * boost : d
}

/**
 * Distance to travel along the cursor ray for `notches` of wheel (positive =
 * zoom in / toward the cursor).
 *
 * Exponential in the notch count, so a single fast trackpad flick can approach
 * but never leap past `navScale` in one event, while a zoom-out retraces at the
 * mirror-image rate. Because navScale is measured against the *structure* and
 * not the orbit target, this never decays to zero — the camera flies through.
 */
export function zoomStep(navScale, notches, zoomFrac) {
  if (!Number.isFinite(navScale) || navScale <= 0) return 0
  if (!notches) return 0
  const k = 1 - zoomFrac
  if (k <= 0 || k >= 1) return 0
  return navScale * (1 - Math.pow(k, notches))
}

/**
 * Normalize a wheel event's deltaY into notches (positive = zoom in), clamped so
 * that one high-resolution trackpad event can't teleport the camera.
 *
 * deltaMode: 0 = pixels (trackpads, ~100/notch), 1 = lines, 2 = pages.
 */
export function wheelNotches(deltaY, deltaMode = 0, maxNotch = MULTISCALE_DEFAULTS.maxNotch) {
  const perNotch = deltaMode === 1 ? 3 : deltaMode === 2 ? 1 : 100
  const n = -deltaY / perNotch
  if (n > maxNotch) return maxNotch
  if (n < -maxNotch) return -maxNotch
  return n
}
