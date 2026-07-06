import { describe, it, expect } from 'vitest'
import {
  OXDNA_FORCE_PN, DEFAULT_Q_EFF,
  pnToOxdna, oxdnaToPn, fieldVpmToPn, pnToFieldVpm,
  vecLen, scaleVec, normalize, rayPlaneVector,
  arrowLenForPn, pnForArrowLen, EFIELD_MAX_LEN_NM, EFIELD_MIN_LEN_NM, EFIELD_NM_PER_PN,
  resolveSelectionAnchors, anchorKey, anchorLabel, dedupeAnchors, addAnchors, removeAnchor,
  buildFieldSpec, fieldSpecReady,
  fieldColorHex, fieldZone, EFIELD_PN_LOW, EFIELD_PN_GOOD, EFIELD_PN_DISRUPT,
  anchorAmplification, anchorTensionPn, safePnFor, disruptPnFor,
  nmPerPnFor, nmPerPnForN, fieldZoneFor, fieldColorForHex,
  EFIELD_ANCHOR_SAFE_PN, EFIELD_ANCHOR_DISRUPT_PN, EFIELD_REF_NT,
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
    expect(anchorKey({ kind: 'strand', id: 's7' })).toBe('strand:s7')
    expect(anchorKey({ kind: 'base', helixId: 'h2', bp: 5, direction: 'forward' })).toBe('base:h2:5:forward')
  })
  it('labels are human-readable', () => {
    expect(anchorLabel({ kind: 'overhang', id: 'o1' })).toBe('overhang o1')
    expect(anchorLabel({ kind: 'domain', strandId: 's2', domainIndex: 0 })).toBe('domain s2#0')
    expect(anchorLabel({ kind: 'strand', id: 's7' })).toBe('strand s7')
    expect(anchorLabel({ kind: 'base', helixId: 'h2', bp: 5, direction: 'reverse' })).toBe('base h2.5 reverse')
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
  it('reads whole strands (binding oligos) from multi-select and selectedObject', () => {
    expect(resolveSelectionAnchors({ multiSelectedStrandIds: ['s3', 's4'] }))
      .toEqual([{ kind: 'strand', id: 's3' }, { kind: 'strand', id: 's4' }])
    expect(resolveSelectionAnchors({ selectedObject: { type: 'strand', id: 's8', data: { strand_id: 's8' } } }))
      .toEqual([{ kind: 'strand', id: 's8' }])
  })
  it('reads an individual selected base (nucleotide)', () => {
    expect(resolveSelectionAnchors({
      selectedObject: { type: 'nucleotide', id: 'h1:5:forward',
                        data: { helix_id: 'h1', bp_index: 5, direction: 'forward' } },
    })).toEqual([{ kind: 'base', helixId: 'h1', bp: 5, direction: 'forward' }])
  })
  it('ignores a data-less nucleotide selection and empty state', () => {
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

describe('anchor-bond tension (the destructive axis)', () => {
  // VoltronCore: 14774 nt, 16 anchors, 2.227 pN/nt → ~2055 pN/bond → blow-up.
  const VC = { nTotal: 14774, nAnchored: 16 }

  it('amplification = n_total / n_anchored, multiplying WITH n_total (not 1/n)', () => {
    expect(anchorAmplification(14774, 16)).toBeCloseTo(923.375, 3)
    // bigger structure, same anchors → MORE tension, not less
    expect(anchorAmplification(30000, 16)).toBeGreaterThan(anchorAmplification(14774, 16))
    // more anchors → less tension
    expect(anchorAmplification(14774, 160)).toBeLessThan(anchorAmplification(14774, 16))
    expect(anchorAmplification(0, 16)).toBe(1)       // unknown size → no amplification
    expect(anchorAmplification(100, 0)).toBe(100)    // guards n_anchored≥1
  })

  it('reproduces the VoltronCore tension that blew up (~2055 pN ≫ 243)', () => {
    const T = anchorTensionPn(2.227, VC.nTotal, VC.nAnchored)
    expect(T).toBeGreaterThan(2000)
    expect(T).toBeGreaterThan(EFIELD_ANCHOR_DISRUPT_PN)
  })

  it('safe/disrupt per-nt forces invert the tension thresholds', () => {
    expect(anchorTensionPn(safePnFor(VC), VC.nTotal, VC.nAnchored)).toBeCloseTo(EFIELD_ANCHOR_SAFE_PN, 6)
    expect(anchorTensionPn(disruptPnFor(VC), VC.nTotal, VC.nAnchored)).toBeCloseTo(EFIELD_ANCHOR_DISRUPT_PN, 6)
    // VoltronCore's safe per-nt is tiny — well under the 2.227 the user picked
    expect(safePnFor(VC)).toBeLessThan(0.1)
    expect(disruptPnFor(VC)).toBeLessThan(0.3)
  })
})

describe('structure-aware zone + colour', () => {
  const VC = { nTotal: 14774, nAnchored: 16 }

  it('the 2.227 pN/nt that read green now reads disrupt on VoltronCore', () => {
    expect(fieldZone(2.227)).toBe('good')                 // old per-nt model: looked fine
    expect(fieldZoneFor(2.227, VC)).toBe('disrupt')       // tension model: will blow up
  })

  it('zone partitions on tension; tiny anchored structure tolerates more per-nt', () => {
    // small structure: safe per-nt (~8 pN) sits above the deflect floor, so a real
    // 'good' window exists; VoltronCore's safe per-nt (~0.05) is below it — no green.
    const small = { nTotal: 100, nAnchored: 16 }  // amp 6.25 → safe@8pN, disrupt@38.9pN
    expect(fieldZoneFor(0, small)).toBe('low')
    expect(fieldZoneFor(4, small)).toBe('good')                          // T=25 (<50)
    expect(fieldZoneFor((safePnFor(small) + disruptPnFor(small)) / 2, small)).toBe('strong')
    expect(fieldZoneFor(disruptPnFor(small) * 2, small)).toBe('disrupt')
    // a negligible-looking per-nt force is already strong on the big structure
    expect(fieldZoneFor(0.1, VC)).toBe('strong')                         // T≈92
    // same per-nt force is fine on a 100-nt structure, fatal on a 14k one
    expect(fieldZoneFor(1, small)).toBe('good')
    expect(fieldZoneFor(1, VC)).toBe('disrupt')
  })

  it('falls back to the per-nt heuristic when context is unknown', () => {
    expect(fieldZoneFor(2.227, null)).toBe(fieldZone(2.227))
    expect(fieldZoneFor(2.227, { nTotal: 0, nAnchored: 0 })).toBe(fieldZone(2.227))
    expect(fieldColorForHex(5, null)).toBe(fieldColorHex(5))
  })

  it('colour goes green→red as tension crosses safe→disrupt', () => {
    const RED = 0xdc3c32
    const small = { nTotal: 100, nAnchored: 16 }
    expect(fieldColorForHex(disruptPnFor(VC) * 2, VC)).toBe(RED)        // ≥ disrupt → solid red
    const good = fieldColorForHex(4, small)                            // T=25 (<50) AND f>floor → green
    expect((good >> 8) & 0xff).toBeGreaterThan(good & 0xff)            // green channel dominates blue
  })
})

describe('structure-aware drag scaling', () => {
  const VC = { nTotal: 14774, nAnchored: 16 }

  it('unknown context keeps the flat 4 nm/pN', () => {
    expect(nmPerPnFor(null)).toBe(EFIELD_NM_PER_PN)
    expect(nmPerPnFor({ nTotal: 0, nAnchored: 0 })).toBe(EFIELD_NM_PER_PN)
  })

  it('full arrow length maps to the disrupt force for this design', () => {
    const scale = nmPerPnFor(VC)
    // dragging to the disrupt per-nt saturates the arrow at MAX
    expect(arrowLenForPn(disruptPnFor(VC), scale)).toBeCloseTo(EFIELD_MAX_LEN_NM, 6)
    // and the user's old "small arrow" 2.227 pN now pins past MAX (clamped) → clearly red zone
    expect(arrowLenForPn(2.227, scale)).toBe(EFIELD_MAX_LEN_NM)
    // round-trips with the same scale
    expect(pnForArrowLen(arrowLenForPn(0.1, scale), scale)).toBeCloseTo(0.1, 6)
  })

  it('a lightly-anchored big structure compresses the usable drag range', () => {
    // more anchors → larger disrupt force → gentler (smaller) nm/pN scale
    expect(nmPerPnFor({ nTotal: 14774, nAnchored: 160 }))
      .toBeLessThan(nmPerPnFor({ nTotal: 14774, nAnchored: 16 }))
  })
})

describe('base-count drag scaling (nmPerPnForN)', () => {
  it('unknown / zero base count keeps the flat constant', () => {
    expect(nmPerPnForN(0)).toBe(EFIELD_NM_PER_PN)
    expect(nmPerPnForN(null)).toBe(EFIELD_NM_PER_PN)
    expect(nmPerPnForN(undefined)).toBe(EFIELD_NM_PER_PN)
  })

  it('equals the flat constant at the reference base count', () => {
    expect(nmPerPnForN(EFIELD_REF_NT)).toBeCloseTo(EFIELD_NM_PER_PN, 9)
  })

  it('scales nm/pN proportionally to base count (no floor)', () => {
    // 10× the bases → 10× the nm/pN → 1/10 the per-nt force for the same arrow.
    expect(nmPerPnForN(10 * EFIELD_REF_NT)).toBeCloseTo(10 * EFIELD_NM_PER_PN, 6)
    // below the reference it keeps scaling down (no floor) — small designs coarser.
    expect(nmPerPnForN(EFIELD_REF_NT / 4)).toBeCloseTo(EFIELD_NM_PER_PN / 4, 6)
  })

  it('a given arrow length gives a smaller per-nt force on a bigger design', () => {
    const small = nmPerPnForN(1000)
    const big   = nmPerPnForN(14774)        // VoltronCore
    const lenNm = 30                         // same arrow drag on both
    expect(pnForArrowLen(lenNm, big)).toBeLessThan(pnForArrowLen(lenNm, small))
    // and round-trips with its own scale
    expect(pnForArrowLen(arrowLenForPn(0.3, big), big)).toBeCloseTo(0.3, 6)
  })
})
