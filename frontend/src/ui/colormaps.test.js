// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import {
  COLORMAPS, COLORMAP_LIST, DEFAULT_COLORMAP_FOR,
  normalizeColormap, defaultColormapFor,
  colormapRGB255, colormapHex, colormapRGB, colormapGradientCss,
  loadColormap, saveColormap,
} from './colormaps.js'

describe('colormap registry', () => {
  it('has 10 colormaps, each a non-empty RGB LUT', () => {
    const names = Object.keys(COLORMAPS)
    expect(names.length).toBe(10)
    for (const n of names) {
      const { label, lut } = COLORMAPS[n]
      expect(typeof label).toBe('string')
      expect(lut.length).toBeGreaterThanOrEqual(2)
      for (const stop of lut) {
        expect(stop.length).toBe(3)
        for (const c of stop) { expect(c).toBeGreaterThanOrEqual(0); expect(c).toBeLessThanOrEqual(255) }
      }
    }
  })

  it('COLORMAP_LIST mirrors registry order + labels', () => {
    expect(COLORMAP_LIST.map((c) => c.name)).toEqual(Object.keys(COLORMAPS))
    expect(COLORMAP_LIST[0]).toEqual({ name: 'viridis', label: 'Viridis' })
  })
})

describe('normalizeColormap / defaultColormapFor', () => {
  it('passes through known names, falls back to viridis', () => {
    expect(normalizeColormap('turbo')).toBe('turbo')
    expect(normalizeColormap('nope')).toBe('viridis')
    expect(normalizeColormap(undefined)).toBe('viridis')
  })
  it('per map-type defaults keep each map its own colours', () => {
    expect(defaultColormapFor('flex')).toBe('viridis')
    expect(defaultColormapFor('deviation')).toBe('devramp')
    expect(defaultColormapFor('cando')).toBe('jet')
    expect(defaultColormapFor('unknown')).toBe('viridis')
    expect(DEFAULT_COLORMAP_FOR.deviation).toBe('devramp')
  })
})

describe('colormapRGB255 / colormapHex / colormapRGB', () => {
  it('endpoints match the first/last LUT stop exactly', () => {
    expect(colormapRGB255('viridis', 0)).toEqual([68, 1, 84])
    expect(colormapRGB255('viridis', 1)).toEqual([253, 231, 37])
    expect(colormapHex('viridis', 0)).toBe((68 << 16) | (1 << 8) | 84)
  })
  it('clamps out-of-range t to endpoints', () => {
    expect(colormapRGB255('jet', -5)).toEqual([0, 0, 255])
    expect(colormapRGB255('jet', 9)).toEqual([255, 0, 0])
    expect(colormapRGB255('jet', NaN)).toEqual([0, 0, 255])
  })
  it('interpolates the midpoint of a 3-stop ramp to the middle anchor', () => {
    // devramp middle anchor is the amber stop.
    expect(colormapRGB255('devramp', 0.5)).toEqual([210, 153, 34])
  })
  it('colormapRGB returns 0..1 floats matching the 255 form', () => {
    const [r, g, b] = colormapRGB('viridis', 1)
    expect(r).toBeCloseTo(253 / 255)
    expect(g).toBeCloseTo(231 / 255)
    expect(b).toBeCloseTo(37 / 255)
  })
  it('unknown colormap name falls back to viridis (no throw)', () => {
    expect(colormapHex('bogus', 0)).toBe(colormapHex('viridis', 0))
  })
})

describe('colormapGradientCss', () => {
  it('builds an N-stop linear-gradient with the requested direction', () => {
    const css = colormapGradientCss('viridis', { stops: 5, dir: 'to top' })
    expect(css.startsWith('linear-gradient(to top, ')).toBe(true)
    expect(css.match(/#[0-9a-f]{6}/g).length).toBe(5)
    // first stop = t0 = first LUT anchor #440154
    expect(css).toContain('#440154')
  })
})

describe('per map-type persistence', () => {
  beforeEach(() => { try { window.localStorage.clear() } catch { /* ignore */ } })

  it('loadColormap returns the map-type default when nothing stored', () => {
    expect(loadColormap('deviation')).toBe('devramp')
    expect(loadColormap('flex')).toBe('viridis')
  })
  it('save then load round-trips a valid pick per map-type', () => {
    saveColormap('flex', 'turbo')
    expect(loadColormap('flex')).toBe('turbo')
    // other map-types are unaffected
    expect(loadColormap('deviation')).toBe('devramp')
  })
  it('an invalid stored value is ignored, default returned', () => {
    saveColormap('flex', 'garbage')          // normalized to viridis on save
    expect(loadColormap('flex')).toBe('viridis')
  })
})
