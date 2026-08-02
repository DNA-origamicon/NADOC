import { describe, it, expect } from 'vitest'
import { fovPanScale, PAN_REF_FOV } from './fov_pan.js'
import { dollyDistanceForFov } from './photo_renderer/figure_camera.js'

describe('fovPanScale', () => {
  it('is exactly 1 at the reference lens', () => {
    expect(fovPanScale(PAN_REF_FOV)).toBeCloseTo(1, 12)
  })

  it('shrinks pan on a long lens and grows it on a wide one', () => {
    expect(fovPanScale(8)).toBeLessThan(1)
    expect(fovPanScale(90)).toBeGreaterThan(1)
  })

  it('cancels the photo-mode dolly exactly — same on-screen pan at any FOV', () => {
    // Photo mode dollies to preserve framing, so the distance-based pan speed
    // (dist × factor) must come out identical at every lens.
    const dist55 = 100
    const at = fov => dollyDistanceForFov(dist55, PAN_REF_FOV, fov) * fovPanScale(fov)
    for (const fov of [4, 8, 20, 35, 55, 75, 90]) {
      expect(at(fov)).toBeCloseTo(dist55, 6)
    }
  })

  it('falls back to 1 on a degenerate FOV instead of freezing or exploding pan', () => {
    expect(fovPanScale(0)).toBe(1)
    expect(fovPanScale(-10)).toBe(1)
    expect(fovPanScale(NaN)).toBe(1)
    expect(fovPanScale(180)).toBe(1)      // tan(90°) is not finite
  })

  it('honours an explicit reference lens', () => {
    expect(fovPanScale(20, 20)).toBeCloseTo(1, 12)
    expect(fovPanScale(55, 20)).toBeGreaterThan(1)
  })
})
