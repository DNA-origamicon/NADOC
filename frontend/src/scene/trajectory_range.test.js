import { describe, it, expect } from 'vitest'
import { clampFrame, frameAtProgress, clampRange, formatJobTime, strideIndices, nearestOf } from './trajectory_range.js'

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
