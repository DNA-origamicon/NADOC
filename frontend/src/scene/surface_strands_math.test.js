import { describe, it, expect } from 'vitest'
import {
  mulberry32, sanitizeSequence, surfaceStrandArea, surfaceStrandCount,
  surfaceStrandPlacements, surfaceStrandsSpec, NM2_PER_UM2, MIN_SPACING_NM,
  captureStrandLocalBeads, BFORM_RISE_NM, BFORM_RADIUS_NM,
  captureNucleotidesFromChains,
} from './surface_strands_math.js'

describe('mulberry32', () => {
  it('is deterministic for a given seed', () => {
    const a = mulberry32(42); const b = mulberry32(42)
    const seqA = [a(), a(), a(), a()]
    const seqB = [b(), b(), b(), b()]
    expect(seqA).toEqual(seqB)
  })
  it('differs across seeds and stays in [0,1)', () => {
    const a = mulberry32(1); const b = mulberry32(2)
    const va = a(); const vb = b()
    expect(va).not.toBe(vb)
    for (const v of [va, vb]) { expect(v).toBeGreaterThanOrEqual(0); expect(v).toBeLessThan(1) }
  })
})

describe('sanitizeSequence', () => {
  it('upper-cases and drops non-ACGT', () => {
    expect(sanitizeSequence('acgt')).toBe('ACGT')
    expect(sanitizeSequence('AC-GT xu 5')).toBe('ACGT')
    expect(sanitizeSequence(null)).toBe('')
  })
})

describe('surfaceStrandArea', () => {
  it('circle uses π(d/2)² (size = diameter), square uses side²', () => {
    expect(surfaceStrandArea({ shape: 'circle', sizeNm: 10 })).toBeCloseTo(Math.PI * 25, 9)
    expect(surfaceStrandArea({ shape: 'square', sizeNm: 10 })).toBe(100)
  })
  it('is 0 for a non-positive size', () => {
    expect(surfaceStrandArea({ shape: 'circle', sizeNm: 0 })).toBe(0)
    expect(surfaceStrandArea({ shape: 'square', sizeNm: -3 })).toBe(0)
  })
})

describe('surfaceStrandCount', () => {
  it('rounds density × area / 1e6', () => {
    // square 100 nm side = 1e4 nm² = 0.01 µm²; 1000 /µm² → 10 strands
    expect(surfaceStrandCount({ shape: 'square', sizeNm: 100, densityPerUm2: 1000 })).toBe(10)
  })
  it('scales linearly with density', () => {
    const c1 = surfaceStrandCount({ shape: 'square', sizeNm: 100, densityPerUm2: 1000 })
    const c2 = surfaceStrandCount({ shape: 'square', sizeNm: 100, densityPerUm2: 2000 })
    expect(c2).toBe(2 * c1)
  })
  it('is 0 when density or size is 0', () => {
    expect(surfaceStrandCount({ shape: 'circle', sizeNm: 50, densityPerUm2: 0 })).toBe(0)
    expect(surfaceStrandCount({ shape: 'circle', sizeNm: 0, densityPerUm2: 5000 })).toBe(0)
  })
  it('NM2_PER_UM2 is 1e6', () => { expect(NM2_PER_UM2).toBe(1e6) })
})

describe('surfaceStrandPlacements', () => {
  it('returns exactly `count` points and is seed-reproducible', () => {
    const args = { shape: 'circle', sizeNm: 50, seed: 7, count: 20 }
    const p1 = surfaceStrandPlacements(args)
    const p2 = surfaceStrandPlacements(args)
    expect(p1).toHaveLength(20)
    expect(p1).toEqual(p2)
  })
  it('keeps circle points within the radius = diameter/2 (plus offset centre)', () => {
    const pts = surfaceStrandPlacements({ shape: 'circle', sizeNm: 60, seed: 3, count: 50, offsetXNm: 5, offsetYNm: -8 })
    for (const p of pts) {
      const r = Math.hypot(p.x - 5, p.y - (-8))
      expect(r).toBeLessThanOrEqual(30 + 1e-9)   // radius = 60/2
    }
  })
  it('enforces the minimum centre-to-centre spacing', () => {
    const pts = surfaceStrandPlacements({ shape: 'square', sizeNm: 60, seed: 5, count: 80 })
    expect(pts.length).toBeGreaterThan(10)
    for (let i = 0; i < pts.length; i++)
      for (let j = i + 1; j < pts.length; j++)
        expect(Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y)).toBeGreaterThanOrEqual(MIN_SPACING_NM - 1e-9)
  })
  it('caps the count when the patch saturates at the min spacing', () => {
    // A tiny patch can't hold 500 strands 2 nm apart — best-effort returns fewer.
    const pts = surfaceStrandPlacements({ shape: 'square', sizeNm: 10, seed: 1, count: 500 })
    expect(pts.length).toBeLessThan(500)
    expect(pts.length).toBeGreaterThan(0)
  })
  it('keeps square points within the half-side about the offset centre', () => {
    const pts = surfaceStrandPlacements({ shape: 'square', sizeNm: 40, seed: 9, count: 200, offsetXNm: 2, offsetYNm: 2 })
    for (const p of pts) {
      expect(Math.abs(p.x - 2)).toBeLessThanOrEqual(20 + 1e-9)
      expect(Math.abs(p.y - 2)).toBeLessThanOrEqual(20 + 1e-9)
    }
  })
  it('is empty when count/size resolves to 0', () => {
    expect(surfaceStrandPlacements({ shape: 'circle', sizeNm: 0, seed: 1, count: 10 })).toEqual([])
    expect(surfaceStrandPlacements({ shape: 'circle', sizeNm: 10, densityPerUm2: 0, seed: 1 })).toEqual([])
  })
  it('derives count from density when `count` is omitted', () => {
    const pts = surfaceStrandPlacements({ shape: 'square', sizeNm: 100, densityPerUm2: 1000, seed: 1 })
    expect(pts).toHaveLength(10)
  })
})

describe('captureStrandLocalBeads', () => {
  it('returns nBeads offsets, bead 0 on the plane, axial rise = B-DNA rise', () => {
    const b = captureStrandLocalBeads(8)
    expect(b).toHaveLength(8)
    expect(b[0].axial).toBe(0)
    expect(b[1].axial - b[0].axial).toBeCloseTo(BFORM_RISE_NM, 9)
    expect(b[7].axial).toBeCloseTo(7 * BFORM_RISE_NM, 9)
  })
  it('places the backbone at the helix radius (1 nm) from the axis', () => {
    for (const bead of captureStrandLocalBeads(5))
      expect(Math.hypot(bead.du, bead.dv)).toBeCloseTo(BFORM_RADIUS_NM, 9)
  })
  it('is empty for 0 / negative', () => {
    expect(captureStrandLocalBeads(0)).toEqual([])
    expect(captureStrandLocalBeads(-3)).toEqual([])
  })
})

describe('captureNucleotidesFromChains', () => {
  const chains = [[[0, 0, 0], [0, 1, 0], [0, 2, 0]], [[5, 0, 0], [5, 1, 0]]]
  it('emits one nuc per bead with the right shape + terminals', () => {
    const nucs = captureNucleotidesFromChains(chains)
    expect(nucs).toHaveLength(5)   // 3 + 2
    expect(nucs[0]).toMatchObject({ helix_id: 'cap0', strand_id: 'cap0', direction: 'FORWARD',
      is_five_prime: true, is_three_prime: false, backbone_position: [0, 0, 0] })
    expect(nucs[2]).toMatchObject({ is_three_prime: true })   // last of strand 0
    expect(nucs[3]).toMatchObject({ helix_id: 'cap1', is_five_prime: true })
  })
  it('gives unique bp_index above the origami range (no slab collision)', () => {
    const bp = captureNucleotidesFromChains(chains).map(n => n.bp_index)
    expect(new Set(bp).size).toBe(bp.length)      // all unique
    expect(Math.min(...bp)).toBeGreaterThanOrEqual(1_000_000)
  })
  it('a1/a3 are unit vectors', () => {
    for (const n of captureNucleotidesFromChains(chains)) {
      expect(Math.hypot(...n.axis_tangent)).toBeCloseTo(1, 6)
      expect(Math.hypot(...n.base_normal)).toBeCloseTo(1, 6)
    }
  })
  it('is empty for empty/invalid input', () => {
    expect(captureNucleotidesFromChains([])).toEqual([])
    expect(captureNucleotidesFromChains(null)).toEqual([])
  })
})

describe('surfaceStrandsSpec', () => {
  it('returns null when disabled/absent', () => {
    expect(surfaceStrandsSpec({ enabled: false })).toBeNull()
    expect(surfaceStrandsSpec(null)).toBeNull()
  })
  it('normalizes fields and attaches count', () => {
    const s = surfaceStrandsSpec({
      enabled: true, sequence: 'gc-ta', attachEnd: "3'", shape: 'square',
      sizeNm: '100', densityPerUm2: '1000', offsetXNm: '4', offsetYNm: -2, seed: 7,
    })
    expect(s).toMatchObject({
      enabled: true, sequence: 'GCTA', attachEnd: "3'", shape: 'square',
      sizeNm: 100, densityPerUm2: 1000, offsetXNm: 4, offsetYNm: -2, seed: 7, count: 10,
    })
    expect(s.subjectToField).toBe(true)   // defaults on
  })
  it('falls back to safe defaults for bad enums and respects subjectToField=false', () => {
    const s = surfaceStrandsSpec({ enabled: true, shape: 'triangle', attachEnd: 'x', subjectToField: false })
    expect(s.shape).toBe('circle')
    expect(s.attachEnd).toBe("5'")
    expect(s.subjectToField).toBe(false)
  })
})
