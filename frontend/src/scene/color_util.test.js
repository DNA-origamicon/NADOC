import { describe, it, expect } from 'vitest'
import { heatmapHex, hexFromInt, atomColorsFromLetters, BASE_HEX } from './color_util.js'

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

describe('hexFromInt', () => {
  it('formats a packed int as #rrggbb', () => {
    expect(hexFromInt(0x74b9ff)).toBe('#74b9ff')
    expect(hexFromInt(0x000000)).toBe('#000000')
    expect(hexFromInt(0xffffff)).toBe('#ffffff')
  })
  it('zero-pads low values to 6 digits', () => {
    expect(hexFromInt(0x0000ff)).toBe('#0000ff')
    expect(hexFromInt(0xff)).toBe('#0000ff')
  })
  it('masks negatives and over-range ints to 24 bits', () => {
    expect(hexFromInt(-1)).toBe('#ffffff')          // (-1 >>> 0) & 0xffffff
    expect(hexFromInt(0x1abcdef)).toBe('#abcdef')   // high bits dropped
  })
})

describe('atomColorsFromLetters', () => {
  it('keys colours by strand:bp:dir using the base palette', () => {
    const nucLetter = new Map([
      [{ strand_id: 's1', bp_index: 0, direction: 'FORWARD' }, 'A'],
      [{ strand_id: 's1', bp_index: 1, direction: 'REVERSE' }, 'G'],
    ])
    const out = atomColorsFromLetters(nucLetter)
    expect(out.get('s1:0:FORWARD')).toBe(BASE_HEX.A)
    expect(out.get('s1:1:REVERSE')).toBe(BASE_HEX.G)
    expect(out.size).toBe(2)
  })
  it('returns an empty map for null/empty input', () => {
    expect(atomColorsFromLetters(null).size).toBe(0)
    expect(atomColorsFromLetters([]).size).toBe(0)
  })
})
