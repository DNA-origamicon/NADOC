import { describe, it, expect } from 'vitest'
import { clampFrame, frameAtProgress, clampRange, formatJobTime, strideIndices, nearestOf,
         trajectorySampling, trajectorySamplingPlan } from './trajectory_range.js'

describe('clampFrame', () => {
  it('clamps into [0, n-1] and rounds', () => {
    expect(clampFrame(-3, 10)).toBe(0)
    expect(clampFrame(99, 10)).toBe(9)
    expect(clampFrame(4.6, 10)).toBe(5)
  })
  it('returns 0 for an empty trajectory', () => {
    expect(clampFrame(5, 0)).toBe(0)
    expect(clampFrame(5, -1)).toBe(0)
  })
})

describe('frameAtProgress', () => {
  it('maps p=0→start, p=1→end, midpoint rounds', () => {
    expect(frameAtProgress(10, 20, 0)).toBe(10)
    expect(frameAtProgress(10, 20, 1)).toBe(20)
    expect(frameAtProgress(10, 20, 0.5)).toBe(15)
    expect(frameAtProgress(10, 21, 0.5)).toBe(16) // 15.5 → 16
  })
  it('clamps p outside [0,1]', () => {
    expect(frameAtProgress(10, 20, -1)).toBe(10)
    expect(frameAtProgress(10, 20, 2)).toBe(20)
  })
  it('handles reversed ranges (start > end)', () => {
    expect(frameAtProgress(20, 10, 0)).toBe(20)
    expect(frameAtProgress(20, 10, 1)).toBe(10)
    expect(frameAtProgress(20, 10, 0.5)).toBe(15)
  })
  it('start===end is constant', () => {
    expect(frameAtProgress(7, 7, 0.3)).toBe(7)
  })
})

describe('clampRange', () => {
  it('defaults missing start→0 and end→last frame', () => {
    expect(clampRange(null, null, 50)).toEqual({ start: 0, end: 49 })
    expect(clampRange(undefined, undefined, 50)).toEqual({ start: 0, end: 49 })
  })
  it('clamps both ends into range, preserving order', () => {
    expect(clampRange(-5, 999, 50)).toEqual({ start: 0, end: 49 })
    expect(clampRange(30, 10, 50)).toEqual({ start: 30, end: 10 })
  })
  it('empty trajectory → {0,0}', () => {
    expect(clampRange(3, 9, 0)).toEqual({ start: 0, end: 0 })
  })
})

describe('strideIndices', () => {
  it('returns endpoints + evenly spaced interior, capped at maxCount', () => {
    expect(strideIndices(0, 100, 5)).toEqual([0, 25, 50, 75, 100])
    expect(strideIndices(10, 20, 3)).toEqual([10, 15, 20])
  })
  it('never exceeds the available frames in the span', () => {
    expect(strideIndices(0, 3, 100)).toEqual([0, 1, 2, 3])
  })
  it('order-insensitive (start>end) and single-frame spans', () => {
    expect(strideIndices(20, 10, 3)).toEqual([10, 15, 20])
    expect(strideIndices(7, 7, 5)).toEqual([7])
  })
  it('dedups when rounding collides', () => {
    const out = strideIndices(0, 2, 100)
    expect(new Set(out).size).toBe(out.length)
  })
})

describe('nearestOf', () => {
  it('finds the closest key', () => {
    expect(nearestOf([0, 10, 20, 30], 13)).toBe(10)
    expect(nearestOf([0, 10, 20, 30], 16)).toBe(20)
    expect(nearestOf([0, 10, 20, 30], 30)).toBe(30)
  })
  it('returns null for an empty list', () => {
    expect(nearestOf([], 5)).toBe(null)
    expect(nearestOf(null, 5)).toBe(null)
  })
})

describe('formatJobTime', () => {
  it('formats a unix-seconds stamp as "Mon D HH:MM" (local)', () => {
    const secs = 1_700_000_000 // a real epoch
    const d = new Date(secs * 1000)
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    const pad = (n) => String(n).padStart(2, '0')
    const expected = `${months[d.getMonth()]} ${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    expect(formatJobTime(secs)).toBe(expected)
  })
  it('returns "" for missing/invalid input', () => {
    expect(formatJobTime(null)).toBe('')
    expect(formatJobTime(undefined)).toBe('')
    expect(formatJobTime(NaN)).toBe('')
  })
})

// ── Export resampling ────────────────────────────────────────────────────────

/**
 * A video export resamples the trajectory: it takes `hold × fps + 1` samples across
 * the hold window and asks `frameAtProgress` what to draw at each. Take fewer samples
 * than the range has frames and whole simulated frames are never drawn — silently.
 * Verified against the real thing: 6hbx32 + job 4220ddf73b60 (501 frames, hold 20 s)
 * exported at 30 fps yields exactly 501 distinct images inside a 601-frame GIF.
 */
const kfOf = (hold, start = null, end = null) => ({
  id: 'k1', trajectory_job_id: 'J', hold_duration_s: hold,
  trajectory_frame_start: start, trajectory_frame_end: end,
})

describe('trajectorySampling', () => {
  it('shows every frame when hold × fps covers the range', () => {
    // The measured case: 501 frames, 20 s hold, 30 fps → 601 samples.
    const r = trajectorySampling(kfOf(20), 501, 30)
    expect(r.frames).toBe(501)
    expect(r.samples).toBe(601)
    expect(r.shown).toBe(501)
    expect(r.dropped).toBe(0)
    expect(r.ok).toBe(true)
  })

  it('drops frames when the capture rate is too low for the hold', () => {
    // Halving fps to shrink the GIF silently throws away 60% of the simulation.
    const r = trajectorySampling(kfOf(20), 501, 10)
    expect(r.samples).toBe(201)
    expect(r.shown).toBe(201)
    expect(r.dropped).toBe(300)
    expect(r.ok).toBe(false)
  })

  it('reports the rate that would just cover the range', () => {
    expect(trajectorySampling(kfOf(20), 501, 10).minFps).toBe(25)
    // …and it is sufficient, not merely necessary.
    expect(trajectorySampling(kfOf(20), 501, 25).ok).toBe(true)
    expect(trajectorySampling(kfOf(20), 501, 24).ok).toBe(false)
  })

  it('reports the hold that would cover the range at the chosen rate', () => {
    expect(trajectorySampling(kfOf(5), 501, 10).minHoldS).toBe(50)
  })

  it('is exactly at the boundary: hold × fps === frames − 1 is enough', () => {
    expect(trajectorySampling(kfOf(10), 101, 10).ok).toBe(true)   // 101 samples, 101 frames
    expect(trajectorySampling(kfOf(10), 102, 10).ok).toBe(false)  // 101 samples, 102 frames
  })

  it('honours an authored sub-range rather than the whole trajectory', () => {
    const r = trajectorySampling(kfOf(2, 100, 149), 501, 10)
    expect(r.frames).toBe(50)          // not 501
    expect(r.ok).toBe(false)           // 21 samples < 50
    expect(r.minFps).toBe(25)
  })

  it('handles a reversed range (end before start)', () => {
    expect(trajectorySampling(kfOf(2, 149, 100), 501, 10).frames).toBe(50)
  })

  it('flags heavy oversampling — every frame shown, but held unevenly', () => {
    // 601 samples over 50 frames: each frame lands 12 or 13 times, so the motion
    // judders even though nothing is dropped.
    const r = trajectorySampling(kfOf(20, 0, 49), 501, 30)
    expect(r.ok).toBe(true)
    expect(r.oversampled).toBe(true)
    expect(trajectorySampling(kfOf(20), 501, 30).oversampled).toBe(false)
  })

  it('a zero-length hold can show only one frame, at any rate', () => {
    const r = trajectorySampling(kfOf(0), 501, 60)
    expect(r.samples).toBe(1)
    expect(r.shown).toBe(1)
    expect(r.minFps).toBe(Infinity)
    expect(r.ok).toBe(false)
  })
})

describe('trajectorySamplingPlan', () => {
  const anim = (...kfs) => ({ keyframes: kfs })

  it('is ok when every trajectory keyframe is covered', () => {
    const p = trajectorySamplingPlan(anim(kfOf(20), { id: 'plain' }), () => 501, 30)
    expect(p.ok).toBe(true)
    expect(p.rows).toHaveLength(1)     // the non-trajectory keyframe is not a row
    expect(p.worst).toBe(null)
  })

  it('names the keyframe dropping the most frames, and one rate that fixes all', () => {
    const a = anim(
      { ...kfOf(20), id: 'big' },
      { ...kfOf(4), id: 'small', trajectory_job_id: 'K' },
    )
    const p = trajectorySamplingPlan(a, (j) => (j === 'J' ? 501 : 101), 10)
    expect(p.ok).toBe(false)
    expect(p.worst.kfId).toBe('big')   // 300 dropped vs 60
    expect(p.minFps).toBe(25)          // max(25, 25)
  })

  it('skips keyframes whose trajectory has not loaded rather than guessing', () => {
    const p = trajectorySamplingPlan(anim(kfOf(20)), () => 0, 10)
    expect(p.rows).toHaveLength(0)
    expect(p.ok).toBe(true)
  })
})
