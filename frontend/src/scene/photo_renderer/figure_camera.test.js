import { describe, it, expect } from 'vitest'
import { dollyDistanceForFov, PARALLEL_FOV, PERSPECTIVE_FOV } from './figure_camera.js'

const DEG2RAD = Math.PI / 180
// Apparent half-height of the subject at a given distance/FOV. The dolly is
// correct exactly when this is invariant across the FOV change.
const halfHeight = (dist, fovDeg) => dist * Math.tan((fovDeg * DEG2RAD) / 2)

describe('dollyDistanceForFov', () => {
  it('is a no-op when the FOV does not change', () => {
    expect(dollyDistanceForFov(100, 55, 55)).toBeCloseTo(100, 9)
  })

  it('preserves apparent subject size — the whole point of the dolly', () => {
    const before = halfHeight(100, 55)
    const after  = halfHeight(dollyDistanceForFov(100, 55, PARALLEL_FOV), PARALLEL_FOV)
    expect(after).toBeCloseTo(before, 9)
  })

  it('moves the camera BACK for a longer lens (narrower FOV)', () => {
    const d = dollyDistanceForFov(100, 55, 8)
    expect(d).toBeGreaterThan(100)
    // 55° → 8° is roughly a 7.4× pull-back: tan(27.5°)/tan(4°).
    expect(d).toBeCloseTo(100 * Math.tan(27.5 * DEG2RAD) / Math.tan(4 * DEG2RAD), 6)
  })

  it('moves the camera IN for a wider FOV', () => {
    expect(dollyDistanceForFov(100, 8, 55)).toBeLessThan(100)
  })

  it('round-trips: parallel then back to perspective returns the original distance', () => {
    const out  = dollyDistanceForFov(100, PERSPECTIVE_FOV, PARALLEL_FOV)
    const back = dollyDistanceForFov(out, PARALLEL_FOV, PERSPECTIVE_FOV)
    expect(back).toBeCloseTo(100, 6)
  })

  it('returns the distance unchanged rather than NaN/Infinity on degenerate input', () => {
    expect(dollyDistanceForFov(100, 55, 0)).toBe(100)     // zero FOV → tan = 0
    expect(dollyDistanceForFov(100, 0, 55)).toBe(100)
    expect(dollyDistanceForFov(0, 55, 8)).toBe(0)         // camera sitting on the target
    expect(dollyDistanceForFov(100, 55, -10)).toBe(100)   // negative FOV
  })
})

describe('constants', () => {
  it('the parallel lens is long enough to read as parallel but not so long it flies away', () => {
    expect(PARALLEL_FOV).toBeGreaterThan(0)
    expect(PARALLEL_FOV).toBeLessThan(15)
    expect(PERSPECTIVE_FOV).toBeGreaterThan(PARALLEL_FOV)
  })
})
