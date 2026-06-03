import { describe, it, expect } from 'vitest'
import { heatmapHex } from './color_util.js'

const rgb = (hex) => [(hex >> 16) & 0xff, (hex >> 8) & 0xff, hex & 0xff]

describe('heatmapHex', () => {
  it('returns a packed 0xRRGGBB int in range', () => {
    const h = heatmapHex(30)
    expect(Number.isInteger(h)).toBe(true)
    expect(h).toBeGreaterThanOrEqual(0)
    expect(h).toBeLessThanOrEqual(0xffffff)
  })

  it('clamps at/below the min (14 nt) to the blue end (hue 240)', () => {
    // t=0 → hue 240 → pure-ish blue: B dominant, R ~0.
    const [r, g, b] = rgb(heatmapHex(14))
    expect(b).toBeGreaterThan(r)
    expect(b).toBeGreaterThan(g)
    expect(heatmapHex(5)).toBe(heatmapHex(14)) // clamped below min
  })

  it('clamps at/above the max (60 nt) to the red end (hue 0)', () => {
    const [r, g, b] = rgb(heatmapHex(60))
    expect(r).toBeGreaterThan(g)
    expect(r).toBeGreaterThan(b)
    expect(heatmapHex(120)).toBe(heatmapHex(60)) // clamped above max
  })

  it('is monotonic-ish: midpoint differs from both ends', () => {
    expect(heatmapHex(37)).not.toBe(heatmapHex(14))
    expect(heatmapHex(37)).not.toBe(heatmapHex(60))
  })
})
