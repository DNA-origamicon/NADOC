import { describe, it, expect } from 'vitest'
import {
  OXDNA_FORCE_PN, DEFAULT_Q_EFF,
  pnToOxdna, oxdnaToPn, fieldVpmToPn, pnToFieldVpm,
  vecLen, scaleVec, normalize, rayPlaneVector,
  arrowLenForPn, pnForArrowLen, EFIELD_MAX_LEN_NM,
  resolveSelectionAnchors, anchorKey, anchorLabel, dedupeAnchors, addAnchors, removeAnchor,
  buildFieldSpec, fieldSpecReady,
  fieldColorHex, fieldZone, EFIELD_PN_LOW, EFIELD_PN_GOOD, EFIELD_PN_DISRUPT,
} from './efield_math.js'

describe('force-unit conversions', () => {
  it('pN ⇄ oxDNA force units round-trips through 48.63', () => {
    expect(pnToOxdna(OXDNA_FORCE_PN)).toBeCloseTo(1, 9)
    expect(oxdnaToPn(1)).toBeCloseTo(OXDNA_FORCE_PN, 9)
    expect(oxdnaToPn(pnToOxdna(12.3))).toBeCloseTo(12.3, 9)
  })
  it('non-numeric input is treated as 0', () => {
    expect(pnToOxdna(undefined)).toBe(0)
    expect(oxdnaToPn(NaN)).toBe(0)
  })
})

describe('field ⇄ force conversion', () => {
  it('F = q_eff·e·E gives ~0.04005 pN at 1e6 V/m, q_eff=0.25', () => {
    expect(fieldVpmToPn(1e6, 0.25)).toBeCloseTo(0.0400544, 6)
  })
  it('defaults to the Manning q_eff', () => {
    expect(fieldVpmToPn(1e6)).toBeCloseTo(fieldVpmToPn(1e6, DEFAULT_Q_EFF), 12)
  })
  it('inverts cleanly', () => {
    expect(pnToFieldVpm(fieldVpmToPn(5e5, 0.3), 0.3)).toBeCloseTo(5e5, 3)
  })
  it('zero q_eff cannot invert (guards /0)', () => {
    expect(pnToFieldVpm(1, 0)).toBe(0)
  })
})

describe('vector helpers', () => {
  it('vecLen / normalize / scaleVec', () => {
    expect(vecLen([3, 4, 0])).toBeCloseTo(5)
    expect(normalize([0, 0, 5])).toEqual([0, 0, 1])
    expect(scaleVec([1, 2, 3], 2)).toEqual([2, 4, 6])
  })
  it('normalize of a ~zero vector returns zero (no NaN)', () => {
    expect(normalize([0, 0, 0])).toEqual([0, 0, 0])
  })
})

describe('rayPlaneVector', () => {
  it('returns the in-plane offset from the plane point to the hit', () => {
    // ray straight down -Z from (1,2,10); plane z=0 with normal +Z through origin.
    const v = rayPlaneVector([1, 2, 10], [0, 0, -1], [0, 0, 1], [0, 0, 0])
    expect(v[0]).toBeCloseTo(1)
    expect(v[1]).toBeCloseTo(2)
    expect(v[2]).toBeCloseTo(0)
  })
  it('null when the ray is parallel to the plane', () => {
    expect(rayPlaneVector([0, 0, 5], [1, 0, 0], [0, 0, 1], [0, 0, 0])).toBeNull()
  })
  it('null when the hit is behind the ray origin', () => {
    expect(rayPlaneVector([0, 0, 10], [0, 0, 1], [0, 0, 1], [0, 0, 0])).toBeNull()
  })
})

describe('arrow length ⇄ magnitude', () => {
  it('floors at the minimum so direction stays visible at 0 pN', () => {
    expect(arrowLenForPn(0)).toBe(2)
    expect(pnForArrowLen(2)).toBe(0)
  })
  it('round-trips above the floor', () => {
    expect(pnForArrowLen(arrowLenForPn(3))).toBeCloseTo(3, 9)
  })
  it('caps at the maximum length', () => {
    expect(arrowLenForPn(1e9)).toBe(EFIELD_MAX_LEN_NM)
  })
})

describe('anchor descriptors', () => {
  it('keys distinguish kind + id, and domain by strand/index', () => {
    expect(anchorKey({ kind: 'overhang', id: 'o1' })).toBe('overhang:o1')
    expect(anchorKey({ kind: 'cluster', id: 'c1' })).toBe('cluster:c1')
    expect(anchorKey({ kind: 'domain', strandId: 's1', domainIndex: 3 })).toBe('domain:s1:3')
  })
  it('labels are human-readable', () => {
    expect(anchorLabel({ kind: 'overhang', id: 'o1' })).toBe('overhang o1')
    expect(anchorLabel({ kind: 'domain', strandId: 's2', domainIndex: 0 })).toBe('domain s2#0')
  })
  it('dedupe keeps first-seen order', () => {
    const out = dedupeAnchors([
      { kind: 'overhang', id: 'o1' },
      { kind: 'overhang', id: 'o1' },
      { kind: 'cluster', id: 'c1' },
    ])
    expect(out.map(anchorKey)).toEqual(['overhang:o1', 'cluster:c1'])
  })
  it('add merges without dupes; remove drops by key', () => {
    let a = addAnchors([{ kind: 'overhang', id: 'o1' }], [{ kind: 'overhang', id: 'o1' }, { kind: 'cluster', id: 'c1' }])
    expect(a.map(anchorKey)).toEqual(['overhang:o1', 'cluster:c1'])
    a = removeAnchor(a, 'overhang:o1')
    expect(a.map(anchorKey)).toEqual(['cluster:c1'])
  })
})

describe('resolveSelectionAnchors', () => {
  it('pulls overhangs + domains from multi-select and cluster from selectedObject', () => {
    const out = resolveSelectionAnchors({
      multiSelectedOverhangIds: ['o1', 'o2'],
      multiSelectedDomainIds: [{ strandId: 's1', domainIndex: 3 }],
      selectedObject: { type: 'cluster', id: 'c1' },
    })
    expect(out.map(anchorKey).sort()).toEqual(
      ['cluster:c1', 'domain:s1:3', 'overhang:o1', 'overhang:o2'].sort(),
    )
  })
  it('reads a single selected overhang / domain', () => {
    expect(resolveSelectionAnchors({ selectedObject: { type: 'overhang', id: 'o9' } }))
      .toEqual([{ kind: 'overhang', id: 'o9' }])
    expect(resolveSelectionAnchors({ selectedObject: { type: 'domain', data: { strand_id: 's5', domain_index: 2 } } }))
      .toEqual([{ kind: 'domain', strandId: 's5', domainIndex: 2 }])
  })
  it('ignores unsupported selection types and empty state', () => {
    expect(resolveSelectionAnchors({ selectedObject: { type: 'nucleotide', id: 'n1' } })).toEqual([])
    expect(resolveSelectionAnchors(null)).toEqual([])
  })
})

describe('magnitude colour grading', () => {
  const R = (hex) => (hex >> 16) & 0xff
  const G = (hex) => (hex >> 8) & 0xff
  const B = (hex) => hex & 0xff

  it('too small → blue, good → green, disrupt → red', () => {
    const small = fieldColorHex(0.1)            // ≤ LOW
    expect(B(small)).toBeGreaterThan(R(small))
    expect(B(small)).toBeGreaterThan(G(small))
    const good = fieldColorHex(EFIELD_PN_GOOD)  // green peak
    expect(G(good)).toBeGreaterThan(R(good))
    expect(G(good)).toBeGreaterThan(B(good))
    const big = fieldColorHex(EFIELD_PN_DISRUPT * 2)  // ≥ DISRUPT
    expect(R(big)).toBeGreaterThan(G(big))
    expect(R(big)).toBeGreaterThan(B(big))
  })

  it('zones partition by threshold', () => {
    expect(fieldZone(0)).toBe('low')
    expect(fieldZone(EFIELD_PN_LOW + 0.01)).toBe('good')
    expect(fieldZone((EFIELD_PN_GOOD + EFIELD_PN_DISRUPT) / 2)).toBe('strong')
    expect(fieldZone(EFIELD_PN_DISRUPT + 1)).toBe('disrupt')
  })
})

describe('field spec + ready gate', () => {
  it('normalizes dir and carries the oxDNA-unit force', () => {
    const spec = buildFieldSpec({ pN: OXDNA_FORCE_PN, dir: [0, 0, 5], anchors: [{ kind: 'overhang', id: 'o1' }] })
    expect(spec.field_pN).toBe(OXDNA_FORCE_PN)
    expect(spec.field_oxdna).toBeCloseTo(1, 9)
    expect(spec.dir).toEqual([0, 0, 1])
  })
  it('clamps negative force to 0 and dedupes anchors', () => {
    const spec = buildFieldSpec({ pN: -3, dir: [1, 0, 0], anchors: [{ kind: 'overhang', id: 'o1' }, { kind: 'overhang', id: 'o1' }] })
    expect(spec.field_pN).toBe(0)
    expect(spec.anchors).toHaveLength(1)
  })
  it('ready requires force > 0, a real direction, AND ≥1 anchor', () => {
    const base = { pN: 1, dir: [0, 1, 0], anchors: [{ kind: 'overhang', id: 'o1' }] }
    expect(fieldSpecReady(buildFieldSpec(base))).toBe(true)
    expect(fieldSpecReady(buildFieldSpec({ ...base, pN: 0 }))).toBe(false)
    expect(fieldSpecReady(buildFieldSpec({ ...base, dir: [0, 0, 0] }))).toBe(false)
    expect(fieldSpecReady(buildFieldSpec({ ...base, anchors: [] }))).toBe(false)
  })
})
