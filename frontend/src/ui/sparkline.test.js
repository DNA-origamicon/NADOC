/**
 * Pure-core tests for the System-monitor sparkline layout (`sparklinePath`).
 * Layout only — the canvas stroking (`drawSparkline`) is a no-op without a 2-D
 * context under jsdom and is exercised by the live app.
 */
import { describe, it, expect } from 'vitest'
import { sparklinePath } from './sparkline.js'

describe('sparklinePath', () => {
  it('empty / all-null input → empty', () => {
    expect(sparklinePath([], 100, 20)).toEqual({ segments: [], empty: true })
    expect(sparklinePath([null, undefined, NaN], 100, 20).empty).toBe(true)
    expect(sparklinePath(null, 100, 20).empty).toBe(true)
  })

  it('single value sits at the right edge, vertically centred (flat)', () => {
    const { segments, empty } = sparklinePath([42], 100, 20, { min: 0, max: 100, pad: 1 })
    expect(empty).toBe(false)
    expect(segments).toHaveLength(1)
    expect(segments[0]).toHaveLength(1)
    const [x, y] = segments[0][0]
    expect(x).toBeCloseTo(99)                    // w - pad, newest at right
    // 42% of the 0..100 range, mapped into [top=1, bottom=19]
    expect(y).toBeCloseTo(19 - 0.42 * 18, 5)
  })

  it('rising values map UP on screen (larger value → smaller pixel y)', () => {
    const { segments } = sparklinePath([0, 50, 100], 100, 20, { min: 0, max: 100, pad: 1 })
    const pts = segments[0]
    expect(pts).toHaveLength(3)
    expect(pts[0][0]).toBeCloseTo(1)             // first at left (x0=pad)
    expect(pts[2][0]).toBeCloseTo(99)            // last at right (x1=w-pad)
    expect(pts[0][1]).toBeGreaterThan(pts[1][1]) // 0% lower on screen than 50%
    expect(pts[1][1]).toBeGreaterThan(pts[2][1]) // 50% lower than 100%
    expect(pts[2][1]).toBeCloseTo(1)             // 100% pinned to the top
    expect(pts[0][1]).toBeCloseTo(19)            // 0% pinned to the bottom
  })

  it('fixed min/max anchors the scale independent of the data', () => {
    // Two flat-ish samples both near the top of a 0..100 scale.
    const { segments } = sparklinePath([90, 95], 100, 20, { min: 0, max: 100, pad: 1 })
    const pts = segments[0]
    expect(pts[0][1]).toBeLessThan(10)           // 90% → high on screen, not autoscaled to mid
    expect(pts[1][1]).toBeLessThan(pts[0][1])    // 95% higher than 90%
  })

  it('a null in the middle breaks the line into two segments (gap, no jump)', () => {
    const { segments } = sparklinePath([10, 20, null, 40, 50], 100, 20, { min: 0, max: 100 })
    expect(segments).toHaveLength(2)
    expect(segments[0]).toHaveLength(2)          // 10, 20
    expect(segments[1]).toHaveLength(2)          // 40, 50
  })
})
