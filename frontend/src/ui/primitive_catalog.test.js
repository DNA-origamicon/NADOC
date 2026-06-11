/**
 * Pure-function tests for the primitive catalog: data shape, lookup, the meta
 * line, the description word-budget spec (3–6 words), and the schematic SVG.
 */
import { describe, it, expect } from 'vitest'
import {
  PRIMITIVES,
  getPrimitive,
  primitiveMeta,
  primitiveThumbSvg,
} from './primitive_catalog.js'

describe('PRIMITIVES catalog', () => {
  it('ships the 6HB and 18HB beams as the seed library', () => {
    const ids = PRIMITIVES.map((p) => p.id)
    expect(ids).toContain('beam_6hb')
    expect(ids).toContain('beam_18hb')
  })

  it('every entry has the required fields', () => {
    for (const p of PRIMITIVES) {
      expect(typeof p.id).toBe('string')
      expect(typeof p.name).toBe('string')
      expect(typeof p.shortName).toBe('string')
      expect(typeof p.description).toBe('string')
      expect(p.helixCount).toBeGreaterThan(0)
      expect(['HONEYCOMB', 'SQUARE']).toContain(p.lattice)
    }
  })

  it('helix counts match the named bundle sizes', () => {
    expect(getPrimitive('beam_6hb').helixCount).toBe(6)
    expect(getPrimitive('beam_18hb').helixCount).toBe(18)
  })

  it('descriptions stay within the 3–6 word budget', () => {
    for (const p of PRIMITIVES) {
      const words = p.description.trim().split(/\s+/)
      expect(words.length).toBeGreaterThanOrEqual(3)
      expect(words.length).toBeLessThanOrEqual(6)
    }
  })
})

describe('getPrimitive', () => {
  it('returns the entry for a known id', () => {
    expect(getPrimitive('beam_6hb').name).toBe('6-Helix Bundle')
  })
  it('returns null for an unknown id', () => {
    expect(getPrimitive('nope')).toBeNull()
  })
})

describe('primitiveMeta', () => {
  it('formats lattice + helix count', () => {
    expect(primitiveMeta(getPrimitive('beam_6hb'))).toBe('Honeycomb · 6 helices')
    expect(primitiveMeta({ lattice: 'SQUARE', helixCount: 4 })).toBe('Square · 4 helices')
  })
})

describe('primitiveThumbSvg', () => {
  it('draws exactly one circle per helix', () => {
    const svg = primitiveThumbSvg(6)
    expect((svg.match(/<circle/g) ?? []).length).toBe(6)
    expect((primitiveThumbSvg(18).match(/<circle/g) ?? []).length).toBe(18)
  })

  it('is a self-contained, sized svg element', () => {
    const svg = primitiveThumbSvg(6, { size: 48 })
    expect(svg.startsWith('<svg')).toBe(true)
    expect(svg).toContain('width="48"')
    expect(svg).toContain('viewBox=')
  })

  it('clamps a zero/negative count to a single circle', () => {
    expect((primitiveThumbSvg(0).match(/<circle/g) ?? []).length).toBe(1)
  })
})
