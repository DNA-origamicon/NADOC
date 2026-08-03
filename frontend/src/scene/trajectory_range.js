/**
 * Pure helpers for mapping a trajectory keyframe's [start,end] frame range onto
 * playback progress. Used by the animation player (to pick which trajectory frame
 * to show at a given moment) and by the panel's range slider.
 *
 * A trajectory keyframe plays frames frameStart → frameEnd across its hold window;
 * progress p ∈ [0,1] is "how far through the hold are we". start may be > end
 * (reverse playback of the range) — the math handles either order.
 */

/** Clamp an integer frame index to [0, nFrames-1]. nFrames<1 → 0. */
export function clampFrame(i, nFrames) {
  const n = Math.max(0, (nFrames | 0))
  if (n < 1) return 0
  return Math.max(0, Math.min(n - 1, Math.round(Number.isFinite(i) ? i : 0)))
}

/**
 * Frame index to show at progress p ∈ [0,1] through a [start,end] range.
 * Rounds to the nearest whole frame; clamps p to [0,1]. Returns start when
 * start===end. Does NOT clamp to a frame count — callers pass already-valid
 * start/end (see clampRange) or clamp the result with clampFrame.
 */
export function frameAtProgress(start, end, p) {
  const s = Math.round(Number.isFinite(start) ? start : 0)
  const e = Math.round(Number.isFinite(end) ? end : s)
  const q = Math.max(0, Math.min(1, Number.isFinite(p) ? p : 0))
  return Math.round(s + (e - s) * q)
}

/**
 * Normalize a (start,end) pair against a known frame count: each clamped to
 * [0,nFrames-1]; missing/NaN start→0, missing end→last frame. Order preserved
 * (start may exceed end). Returns {start, end}.
 */
export function clampRange(start, end, nFrames) {
  const n = Math.max(0, (nFrames | 0))
  if (n < 1) return { start: 0, end: 0 }
  const s = Number.isFinite(start) ? clampFrame(start, n) : 0
  const e = Number.isFinite(end) ? clampFrame(end, n) : n - 1
  return { start: s, end: e }
}

/**
 * Pick ≤ maxCount evenly-spaced integer frame indices spanning [start,end]
 * (inclusive, order-insensitive), for baking heavy reps (atomistic/surface) at a
 * downsampled subset of the playable range. Always includes both endpoints.
 */
export function strideIndices(start, end, maxCount) {
  const s = Math.min(start, end) | 0
  const e = Math.max(start, end) | 0
  const span = e - s
  if (span <= 0) return [s]
  const n = Math.max(1, Math.min(maxCount | 0, span + 1))
  if (n <= 1) return [s]
  const out = []
  for (let i = 0; i < n; i++) out.push(Math.round(s + (span * i) / (n - 1)))
  return [...new Set(out)].sort((a, b) => a - b)
}

/**
 * Will an export at `fps` actually SHOW every simulated frame of this keyframe?
 *
 * A video export samples the timeline at a fixed rate and asks the player what to
 * draw at each instant; the player maps that instant onto the keyframe's frame
 * range with `frameAtProgress`. So the trajectory is resampled, and if the export
 * takes fewer samples across the hold window than the range has frames, whole
 * frames are never drawn — silently, and with no visible artefact beyond the
 * motion looking coarser than the simulation actually was.
 *
 * Samples landing in the hold window ≈ `hold × fps + 1`, spanning `frames`
 * indices, so **every frame appears iff `hold × fps ≥ frames − 1`**.
 *
 * The reverse mismatch is harmless but worth reporting: with far more samples
 * than frames, each frame is held for several samples, and because the count per
 * frame alternates (⌊s/f⌋ and ⌈s/f⌉) the motion judders slightly.
 *
 * @param {object} kf        the keyframe (needs hold_duration_s + the frame range)
 * @param {number} nFrames   frames the loaded trajectory actually has
 * @param {number} fps       export capture rate
 * @returns {{frames:number, samples:number, shown:number, dropped:number,
 *            minFps:number, minHoldS:number, ok:boolean, oversampled:boolean}}
 */
export function trajectorySampling(kf, nFrames, fps) {
  const { start, end } = clampRange(kf?.trajectory_frame_start, kf?.trajectory_frame_end, nFrames)
  const frames = Math.abs(end - start) + 1
  const hold   = Math.max(0, Number(kf?.hold_duration_s) || 0)
  const rate   = Math.max(1, Number(fps) || 0)
  // +1: the capture loop runs i = 0..frameCount inclusive, so a 1 s hold at 10 fps
  // takes 11 samples, not 10.
  const samples = Math.floor(hold * rate) + 1
  const shown   = Math.max(1, Math.min(frames, samples))
  return {
    frames,
    samples,
    shown,
    dropped: frames - shown,
    // Rate that would just cover the range. hold 0 can never be covered by any
    // rate (a zero-length window shows exactly one frame) — report Infinity.
    minFps:   hold > 0 ? Math.ceil((frames - 1) / hold) : Infinity,
    minHoldS: rate > 0 ? (frames - 1) / rate : Infinity,
    ok: shown >= frames,
    oversampled: samples >= 2 * frames && frames > 1,
  }
}

/**
 * Run `trajectorySampling` over every trajectory keyframe of an animation.
 *
 * @param {object}   animation
 * @param {function} frameCountFor  jobId → frames loaded (0 = unknown/not loaded)
 * @param {number}   fps
 * @returns {{ok:boolean, rows:Array, worst:object|null, minFps:number}}
 *   `worst` is the keyframe dropping the most frames; `minFps` is the rate that
 *   would satisfy ALL of them. Keyframes whose frame count is unknown are skipped
 *   rather than guessed at.
 */
export function trajectorySamplingPlan(animation, frameCountFor, fps) {
  const rows = []
  for (const kf of animation?.keyframes ?? []) {
    if (!kf?.trajectory_job_id) continue
    const n = Number(frameCountFor?.(kf.trajectory_job_id)) || 0
    if (n < 1) continue
    rows.push({ kfId: kf.id, jobId: kf.trajectory_job_id, ...trajectorySampling(kf, n, fps) })
  }
  const bad = rows.filter(r => !r.ok)
  const worst = bad.length
    ? bad.reduce((a, b) => (b.dropped > a.dropped ? b : a))
    : null
  const minFps = rows.length
    ? Math.max(...rows.map(r => (Number.isFinite(r.minFps) ? r.minFps : 0)), 1)
    : 1
  return { ok: bad.length === 0, rows, worst, minFps }
}

/** Nearest value in `keys` (array of ints) to `idx`; null for an empty list. */
export function nearestOf(keys, idx) {
  if (!Array.isArray(keys) || !keys.length) return null
  let best = keys[0]
  let bestD = Math.abs(keys[0] - idx)
  for (const k of keys) {
    const d = Math.abs(k - idx)
    if (d < bestD) { bestD = d; best = k }
  }
  return best
}

const _MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/**
 * Format a job's created_at (unix SECONDS) as a short local "Mon D HH:MM" stamp
 * for the trajectory-job dropdown, so the user can tell same-named runs apart.
 * Returns '' for a missing/invalid value.
 */
export function formatJobTime(unixSeconds) {
  if (!Number.isFinite(unixSeconds)) return ''
  const d = new Date(unixSeconds * 1000)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${_MONTHS[d.getMonth()]} ${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
