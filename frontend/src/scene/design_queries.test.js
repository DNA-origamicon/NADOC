import { describe, it, expect } from 'vitest'
import { surfaceSegments, isExtrudeOverhang, ovhgDomainIds, ovhgBinderDomainIds, flexAnchorKey, connIdForBead, flexibleRunForBead, assembleOverhangSequence, overhangHasSequenceOverride, overhangDomainLength, pairingSegments, isComplement, classifyDuplex, classifyAntiparallel, classifyAssemblyDuplex, assemblyOverhangDuplexCoverage, overhangDuplexCoverage, overhangHasDuplex, overhangDuplexSegments, capSequenceToLength, overhangRcOfPartner, duplexClusterForOverhang } from './design_queries.js'

describe('assembleOverhangSequence', () => {
  it('uses the top-level sequence when there are no overrides', () => {
    const oh = { sequence: 'acgt', sub_domains: [{ start_bp_offset: 0, length_bp: 4 }] }
    expect(assembleOverhangSequence(oh)).toBe('ACGT')
  })
  it('pads with N to the domain length', () => {
    const oh = { sequence: 'AC', sub_domains: [{ start_bp_offset: 0, length_bp: 4 }] }
    expect(assembleOverhangSequence(oh, 4)).toBe('ACNN')
  })
  it('reads split sub-domain overrides (the gap this fixes)', () => {
    const oh = { sequence: null, sub_domains: [
      { start_bp_offset: 0, length_bp: 2, sequence_override: 'gg' },
      { start_bp_offset: 2, length_bp: 2, sequence_override: 'TT' },
    ] }
    expect(assembleOverhangSequence(oh)).toBe('GGTT')
  })
  it('mixes override + parent slice per sub-domain', () => {
    const oh = { sequence: 'AAAACCCC', sub_domains: [
      { start_bp_offset: 0, length_bp: 4 },                       // parent slice AAAA
      { start_bp_offset: 4, length_bp: 4, sequence_override: 'gggg' },
    ] }
    expect(assembleOverhangSequence(oh)).toBe('AAAAGGGG')
  })
  it('all-N when neither parent nor overrides set', () => {
    const oh = { sequence: null, sub_domains: [{ start_bp_offset: 0, length_bp: 3 }] }
    expect(assembleOverhangSequence(oh)).toBe('NNN')
  })
  it('returns empty string for a null overhang', () => {
    expect(assembleOverhangSequence(null)).toBe('')
  })
})

describe('overhangHasSequenceOverride', () => {
  it('true when any sub-domain has an override', () => {
    expect(overhangHasSequenceOverride({ sub_domains: [{ sequence_override: 'A' }] })).toBe(true)
  })
  it('false for a whole-overhang (no override)', () => {
    expect(overhangHasSequenceOverride({ sequence: 'ACGT', sub_domains: [{ length_bp: 4 }] })).toBe(false)
  })
})

describe('overhangDomainLength', () => {
  const design = (start, end) => ({
    strands: [
      { domains: [{ helix_id: 'h0' }, { overhang_id: 'oh1', start_bp: start, end_bp: end }] },
    ],
  })
  it('mirrors backend abs(end-start)+1', () => {
    expect(overhangDomainLength(design(0, 3), 'oh1')).toBe(4)   // 4 bp domain
    expect(overhangDomainLength(design(10, 5), 'oh1')).toBe(6)  // reverse-polarity domain
  })
  it('reflects a drag-resized (grown) backing domain', () => {
    // overhang seq is 4 long but the domain was dragged out to 6 bp
    const oh = { sequence: 'ACGT' }
    const len = overhangDomainLength(design(0, 5), 'oh1')
    expect(assembleOverhangSequence(oh, len)).toBe('ACGTNN')
  })
  it('null when no backing domain names the overhang', () => {
    expect(overhangDomainLength(design(0, 3), 'nope')).toBe(null)
    expect(overhangDomainLength(null, 'oh1')).toBe(null)
  })
})

describe('pairingSegments', () => {
  const kinds = (segs) => segs.map(s => `${s.kind}:${s.text}`).join(' ')

  it('marks a fully complementary pair as all paired', () => {
    // A=AAAC (5→>3'), B=GTTT = RC(A). Antiparallel: A[0]A<->B[3]T ✓ ... A[3]C<->B[0]G ✓
    const { a, b } = pairingSegments('AAAC', 'GTTT', 0, 0, 4)
    expect(kinds(a)).toBe('paired:AAAC')
    expect(kinds(b)).toBe('paired:GTTT')
  })

  it('flags a dragged-longer overhang tail as excess (anchored at the bound sub-domain)', () => {
    // A grown to 6 nt: AAAC + NN tail; bound region is the original 4-nt sub-domain.
    const { a } = pairingSegments('AAACNN', 'GTTT', 0, 0, 4)
    expect(kinds(a)).toBe('paired:AAAC excess:NN')
  })

  it('flags a non-complementary base inside the bound region as unpaired', () => {
    // A=AAAA vs B=GTTT (RC(AAAA)=TTTT). A[3]A pairs B[0]G → mismatch; rest pair.
    const { a } = pairingSegments('AAAA', 'GTTT', 0, 0, 4)
    expect(kinds(a)).toBe('paired:AAA unpaired:A')
  })

  it('N inside the bound region never pairs (unpaired, not paired)', () => {
    const { a } = pairingSegments('AANC', 'GNTT', 0, 0, 4)
    // A[2]=N never pairs; its antiparallel partner B[1]=N also non-pairing
    expect(a.some(s => s.kind === 'unpaired' && s.text.includes('N'))).toBe(true)
  })

  it('honors non-zero bound-region starts on each side', () => {
    // bound region = A[2..3]='AC', B[1..2]='GT'; antiparallel A[2]<->B[2], A[3]<->B[1].
    const { a, b } = pairingSegments('TTAC', 'AGTA', 2, 1, 2)
    expect(kinds(a)).toBe('excess:TT paired:AC')
    expect(kinds(b)).toBe('excess:A paired:GT excess:A')
  })

  it('capSequenceToLength: truncate longer, N-pad shorter, keep length (no resize)', () => {
    expect(capSequenceToLength('ACGTACGTAC', 4)).toBe('ACGT')       // longer → truncated
    expect(capSequenceToLength('ACG', 6)).toBe('ACGNNN')            // shorter → N-padded
    expect(capSequenceToLength('ACGT', 4)).toBe('ACGT')             // equal → unchanged
    expect(capSequenceToLength('acgt', 4)).toBe('ACGT')             // upcased
    // The bug: RC of a 24-mer must NOT be allowed to grow a 10-mer overhang.
    expect(capSequenceToLength('N'.repeat(24), 10)).toHaveLength(10)
  })

  it('isComplement: WC only, N never pairs', () => {
    expect(isComplement('A', 'T')).toBe(true)
    expect(isComplement('g', 'c')).toBe(true)
    expect(isComplement('A', 'G')).toBe(false)
    expect(isComplement('N', 'N')).toBe(false)
  })
})

describe('duplex graph (JS mirror of core/duplex.py)', () => {
  // Overhang A forward domain [0,5] (6 bp "AAACGG"), B reverse domain [5,0] (6 bp "GTTTCC").
  const design = (duplexes) => ({
    strands: [
      { id: 'sa', domains: [{ helix_id: 'hA', start_bp: 0, end_bp: 5, overhang_id: 'ohA' }] },
      { id: 'sb', domains: [{ helix_id: 'hB', start_bp: 5, end_bp: 0, overhang_id: 'ohB' }] },
    ],
    overhangs: [
      { id: 'ohA', sequence: 'AAACGG' },
      { id: 'ohB', sequence: 'GTTTCC' },
    ],
    duplexes,
  })
  const dx = (aLo, aHi, bLo, bHi, extra = {}) => ({
    id: 'd1', left: { overhang_id: 'ohA', start_bp: aLo, end_bp: aHi },
    right: { overhang_id: 'ohB', start_bp: bLo, end_bp: bHi }, ...extra,
  })

  it('classifyDuplex: all complementary, antiparallel bp register', () => {
    const d = design([dx(0, 3, 5, 2)])
    const cls = classifyDuplex(d, d.duplexes[0])
    expect(cls.length).toBe(4)
    expect(cls.positions.every(p => p.complementary)).toBe(true)
    expect(cls.positions[0].left_bp).toBe(0)   // left 5' base
    expect(cls.positions[0].right_bp).toBe(2)  // pairs right 3' base
  })

  it('classifyDuplex: counts mismatches (non-complementary partner)', () => {
    const d = { ...design([dx(0, 3, 5, 2)]), overhangs: [{ id: 'ohA', sequence: 'AAACGG' }, { id: 'ohB', sequence: 'AAACCC' }] }
    const cls = classifyDuplex(d, d.duplexes[0])
    expect(cls.positions.filter(p => !p.complementary).length).toBeGreaterThan(0)
  })

  it('overhangDuplexCoverage: 4 bp duplex on 6 bp overhang → 2 bp toehold', () => {
    const d = design([dx(0, 3, 5, 2)])
    const cov = overhangDuplexCoverage(d, 'ohA')
    expect([0, 1, 2, 3].map(bp => cov[bp])).toEqual(['paired', 'paired', 'paired', 'paired'])
    expect([4, 5].map(bp => cov[bp])).toEqual(['unpaired', 'unpaired'])
  })

  it('overhangDuplexCoverage: multivalent disjoint windows both covered', () => {
    const d = design([dx(0, 1, 5, 4), { ...dx(4, 5, 1, 0), id: 'd2' }])
    const cov = overhangDuplexCoverage(d, 'ohA')
    expect(cov[2]).toBe('unpaired')   // middle toehold
    expect(cov[3]).toBe('unpaired')
    expect(cov[0]).not.toBe('unpaired')
    expect(cov[5]).not.toBe('unpaired')
  })

  it('overhangHasDuplex', () => {
    expect(overhangHasDuplex(design([dx(0, 3, 5, 2)]), 'ohA')).toBe(true)
    expect(overhangHasDuplex(design([]), 'ohA')).toBe(false)
  })

  it('duplexClusterForOverhang: matches the driver directly and the driven via domain_ids', () => {
    const d = {
      strands: [{ id: 's1', domains: [{ overhang_id: 'ohDrv' }, { overhang_id: 'ohDvn' }] }],
      cluster_transforms: [
        { id: 'plain', overhang_duplex_driver_id: null, domain_ids: [] },
        { id: 'dc1', overhang_duplex_driver_id: 'ohDrv',
          domain_ids: [{ strand_id: 's1', domain_index: 1 }] },   // domain 1 = ohDvn
      ],
    }
    expect(duplexClusterForOverhang(d, 'ohDrv')?.id).toBe('dc1')   // driver
    expect(duplexClusterForOverhang(d, 'ohDvn')?.id).toBe('dc1')   // driven via domain_ids
    expect(duplexClusterForOverhang(d, 'ohOther')).toBeNull()      // unrelated overhang
    expect(duplexClusterForOverhang({}, 'ohDrv')).toBeNull()       // empty design
  })

  it('overhangDuplexSegments: paired run then toehold run, 5\'→3\'', () => {
    const d = design([dx(0, 3, 5, 2)])
    const segs = overhangDuplexSegments(d, 'ohA')
    expect(segs.map(s => `${s.kind}:${s.text}`)).toEqual(['paired:AAAC', 'toehold:GG'])
  })

  it('overhangRcOfPartner: RC only the paired window, PRESERVE the toehold (keep length)', () => {
    // 4 bp duplex on the 6 bp ohA (window offsets 0-3, toehold "GG" at offsets 4-5).
    // Partner ohB="AAACCC" (non-complementary) so the paired window visibly changes.
    const d = { ...design([dx(0, 3, 5, 2)]), overhangs: [{ id: 'ohA', sequence: 'AAACGG' }, { id: 'ohB', sequence: 'AAACCC' }] }
    // window ← RC of the aligned ohB bases (antiparallel), toehold "GG" untouched.
    expect(overhangRcOfPartner(d, 'ohA', 'ohB')).toBe('GTTTGG')
    // …and the result IS complementary to ohB over the window now.
    const d2 = { ...d, overhangs: [{ id: 'ohA', sequence: 'GTTTGG' }, { id: 'ohB', sequence: 'AAACCC' }] }
    expect(classifyDuplex(d2, d2.duplexes[0]).positions.every(p => p.complementary)).toBe(true)
  })

  it('overhangRcOfPartner: no duplex → full RC over the shorter length (root-aligned)', () => {
    const d = { ...design([]), overhangs: [{ id: 'ohA', sequence: 'AAACGG' }, { id: 'ohB', sequence: 'AAACCC' }] }
    expect(overhangRcOfPartner(d, 'ohA', 'ohB')).toBe('GGGTTT')   // RC(AAACCC)
  })

  it('overhangRcOfPartner: null when the overhang has no backing domain', () => {
    expect(overhangRcOfPartner({ strands: [], overhangs: [], duplexes: [] }, 'ohA', 'ohB')).toBe(null)
  })
})

describe('cross-part assembly duplex (JS mirror of core/assembly_duplex.py)', () => {
  // Split the per-design fixture across TWO instance designs: ohA on iA (forward
  // domain [0,5] "AAACGG"), ohB on iB (reverse domain [5,0] "GTTTCC").
  const designA = {
    strands: [{ id: 'sa', domains: [{ helix_id: 'hA', start_bp: 0, end_bp: 5, overhang_id: 'ohA' }] }],
    overhangs: [{ id: 'ohA', sequence: 'AAACGG' }],
  }
  const designB = {
    strands: [{ id: 'sb', domains: [{ helix_id: 'hB', start_bp: 5, end_bp: 0, overhang_id: 'ohB' }] }],
    overhangs: [{ id: 'ohB', sequence: 'GTTTCC' }],
  }
  const designFor = (iid) => ({ iA: designA, iB: designB }[iid])
  const adx = (aLo, aHi, bLo, bHi, extra = {}) => ({
    id: 'ad1',
    left: { instance_id: 'iA', overhang_id: 'ohA', start_bp: aLo, end_bp: aHi },
    right: { instance_id: 'iB', overhang_id: 'ohB', start_bp: bLo, end_bp: bHi },
    ...extra,
  })

  it('classifyAntiparallel: shared kernel — length + WC counts + antiparallel register', () => {
    const cls = classifyAntiparallel(
      { start_bp: 0, end_bp: 5 }, { start_bp: 5, end_bp: 0 },
      { start_bp: 0, end_bp: 3 }, { start_bp: 5, end_bp: 2 },
      'AAACGG', 'GTTTCC', true,
    )
    expect(cls.length).toBe(4)
    expect(cls.n_complementary).toBe(4)
    expect(cls.n_mismatch).toBe(0)
    expect(cls.positions[0].left_bp).toBe(0)   // left 5' base
    expect(cls.positions[0].right_bp).toBe(2)  // pairs right 3' base
  })

  it('classifyAntiparallel: no domain → empty positions', () => {
    const cls = classifyAntiparallel(null, { start_bp: 5, end_bp: 0 }, { start_bp: 0, end_bp: 3 }, { start_bp: 5, end_bp: 2 }, 'AAAC', 'GTTT', true)
    expect(cls.positions).toEqual([])
    expect(cls.length).toBe(4)
  })

  it('classifyAssemblyDuplex: sources bases from each instance design, all complementary', () => {
    const cls = classifyAssemblyDuplex(designA, designB, adx(0, 3, 5, 2))
    expect(cls.length).toBe(4)
    expect(cls.positions.every(p => p.complementary)).toBe(true)
    expect(cls.positions[0].left_bp).toBe(0)
    expect(cls.positions[0].right_bp).toBe(2)
  })

  it('classifyAssemblyDuplex: mismatch when a side design has a non-complementary base', () => {
    const badB = { ...designB, overhangs: [{ id: 'ohB', sequence: 'AAACCC' }] }
    const cls = classifyAssemblyDuplex(designA, badB, adx(0, 3, 5, 2))
    expect(cls.n_mismatch).toBeGreaterThan(0)
  })

  it('assemblyOverhangDuplexCoverage: 4 bp duplex on 6 bp overhang → 2 bp toehold', () => {
    const assembly = { duplexes: [adx(0, 3, 5, 2)] }
    const cov = assemblyOverhangDuplexCoverage(assembly, 'iA', 'ohA', designFor)
    expect([0, 1, 2, 3].map(bp => cov[bp])).toEqual(['paired', 'paired', 'paired', 'paired'])
    expect([4, 5].map(bp => cov[bp])).toEqual(['unpaired', 'unpaired'])
  })

  it('assemblyOverhangDuplexCoverage: {} when the overhang has no backing domain on its instance', () => {
    expect(assemblyOverhangDuplexCoverage({ duplexes: [] }, 'iA', 'nope', designFor)).toEqual({})
  })
})

describe('surfaceSegments', () => {
  it('collects segments from surface-rep overrides only', () => {
    const design = {
      representation_overrides: [
        { representation: 'surface', segments: [{ a: 1 }, { a: 2 }] },
        { representation: 'cylinder', segments: [{ a: 9 }] },
        { representation: 'surface', segments: [{ a: 3 }] },
      ],
    }
    expect(surfaceSegments(design)).toEqual([{ a: 1 }, { a: 2 }, { a: 3 }])
  })
  it('returns [] for missing overrides', () => {
    expect(surfaceSegments({})).toEqual([])
    expect(surfaceSegments(undefined)).toEqual([])
  })
})

describe('isExtrudeOverhang', () => {
  const overhang = { id: 'o1', helix_id: 'h9', strand_id: 's1' }
  it('true when no scaffold domain occupies the overhang helix', () => {
    const design = { overhangs: [overhang], strands: [{ strand_type: 'staple', domains: [{ helix_id: 'h9' }] }] }
    expect(isExtrudeOverhang('o1', design)).toBe(true)
  })
  it('false when a scaffold domain sits on the overhang helix (inline)', () => {
    const design = { overhangs: [overhang], strands: [{ strand_type: 'scaffold', domains: [{ helix_id: 'h9' }] }] }
    expect(isExtrudeOverhang('o1', design)).toBe(false)
  })
  it('false for an unknown overhang or one without a helix', () => {
    expect(isExtrudeOverhang('nope', { overhangs: [overhang] })).toBe(false)
    expect(isExtrudeOverhang('o2', { overhangs: [{ id: 'o2' }] })).toBe(false)
  })
})

describe('ovhgDomainIds', () => {
  it('returns {strand_id, domain_index} for every domain of the overhang strand', () => {
    const design = { overhangs: [{ id: 'o1', strand_id: 's1' }], strands: [{ id: 's1', domains: [{}, {}, {}] }] }
    expect(ovhgDomainIds('o1', design)).toEqual([
      { strand_id: 's1', domain_index: 0 },
      { strand_id: 's1', domain_index: 1 },
      { strand_id: 's1', domain_index: 2 },
    ])
  })
  it('returns null when the overhang/strand/domains are missing', () => {
    expect(ovhgDomainIds('o1', { overhangs: [] })).toBeNull()
    expect(ovhgDomainIds('o1', { overhangs: [{ id: 'o1', strand_id: 's1' }], strands: [{ id: 's1', domains: [] }] })).toBeNull()
  })
})

describe('ovhgBinderDomainIds', () => {
  it('returns refs for every domain binding the overhang, across strands', () => {
    const design = {
      strands: [
        { id: 'binder', domains: [{ binds_overhang_id: 'o1' }] },
        { id: 'linker', domains: [{ binds_overhang_id: 'o1' }] },
      ],
    }
    expect(ovhgBinderDomainIds('o1', design)).toEqual([
      { strand_id: 'binder', domain_index: 0 },
      { strand_id: 'linker', domain_index: 0 },
    ])
  })
  it('returns only the bound domain indices within a multi-domain strand (end-to-root: root + binder)', () => {
    // mirrors an end-to-root STAPLE: domain 0 = root (no binds), domain 1 = binder.
    const design = {
      strands: [{ id: 's1', domains: [{}, { binds_overhang_id: 'o1' }, { binds_overhang_id: 'other' }] }],
    }
    expect(ovhgBinderDomainIds('o1', design)).toEqual([{ strand_id: 's1', domain_index: 1 }])
  })
  it('returns [] for an unknown overhang, no binders, or missing design', () => {
    expect(ovhgBinderDomainIds('nope', { strands: [{ id: 's1', domains: [{ binds_overhang_id: 'o1' }] }] })).toEqual([])
    expect(ovhgBinderDomainIds('o1', { strands: [{ id: 's1', domains: [{}] }] })).toEqual([])
    expect(ovhgBinderDomainIds('o1', {})).toEqual([])
    expect(ovhgBinderDomainIds(null, { strands: [] })).toEqual([])
  })
})

describe('flexAnchorKey', () => {
  const design = { strands: [{ id: 's1', domains: [{ helix_id: 'hX' }, { helix_id: 'hY' }] }] }
  it('builds helix:bp:dir from the anchor domain', () => {
    expect(flexAnchorKey({ strand_id: 's1', domain_index: 1, bp_index: 4, direction: 'FORWARD' }, design)).toBe('hY:4:FORWARD')
  })
  it('returns null when the strand/domain is missing', () => {
    expect(flexAnchorKey({ strand_id: 'sZ', domain_index: 0 }, design)).toBeNull()
    expect(flexAnchorKey({ strand_id: 's1', domain_index: 9 }, design)).toBeNull()
  })
})

describe('connIdForBead', () => {
  const design = {
    flexible_connections: [
      { id: 'c1', segment_bead_keys: [{ strand_id: 's1', domain_index: 0, bp_index: 3, direction: 'FORWARD' }] },
    ],
  }
  it('finds the connection whose marked run contains the bead', () => {
    expect(connIdForBead({ strand_id: 's1', domain_index: 0, bp_index: 3, direction: 'FORWARD' }, design)).toBe('c1')
  })
  it('returns null when no run contains the bead', () => {
    expect(connIdForBead({ strand_id: 's1', domain_index: 0, bp_index: 99, direction: 'FORWARD' }, design)).toBeNull()
    expect(connIdForBead({ strand_id: 's1', domain_index: 0, bp_index: 3, direction: 'FORWARD' }, {})).toBeNull()
  })
})

describe('flexibleRunForBead', () => {
  // One strand, one FORWARD domain on helix hA spanning bp 0..4 (5 beads).
  const design = { strands: [{ id: 's1', domains: [{ helix_id: 'hA', start_bp: 0, end_bp: 4, direction: 'FORWARD' }] }] }
  const bead = (bp) => ({ strand_id: 's1', domain_index: 0, helix_id: 'hA', bp_index: bp, direction: 'FORWARD' })
  const geom = (unpairedBps) => Array.from({ length: 5 }, (_, bp) =>
    ({ helix_id: 'hA', bp_index: bp, direction: 'FORWARD', is_unpaired: unpairedBps.includes(bp) }))

  it('returns the contiguous unpaired run containing the bead', () => {
    // bps 1,2,3 unpaired; click bp 2 → run = [1,2,3].
    const run = flexibleRunForBead(design, geom([1, 2, 3]), bead(2))
    expect(run.map(r => r.bp_index)).toEqual([1, 2, 3])
    expect(run.every(r => r.strand_id === 's1' && r.domain_index === 0 && r.direction === 'FORWARD')).toBe(true)
  })

  it('stops the run at paired beads on either side', () => {
    // only bps 2,3 unpaired; click bp 3 → run = [2,3] (bp1 paired, bp4 paired).
    expect(flexibleRunForBead(design, geom([2, 3]), bead(3)).map(r => r.bp_index)).toEqual([2, 3])
  })

  it('falls back to the single bead when the clicked bead is not unpaired', () => {
    expect(flexibleRunForBead(design, geom([0, 1]), bead(3)).map(r => r.bp_index)).toEqual([3])
  })

  it('falls back to the single bead when the strand is unknown', () => {
    const run = flexibleRunForBead(design, geom([0]), { ...bead(0), strand_id: 'sZ' })
    expect(run).toEqual([{ strand_id: 'sZ', domain_index: 0, bp_index: 0, direction: 'FORWARD' }])
  })

  it('handles a reverse-direction domain (end_bp < start_bp)', () => {
    const rev = { strands: [{ id: 's1', domains: [{ helix_id: 'hA', start_bp: 4, end_bp: 0, direction: 'FORWARD' }] }] }
    // all unpaired → whole 5-bead run regardless of traversal direction.
    expect(flexibleRunForBead(rev, geom([0, 1, 2, 3, 4]), bead(2)).map(r => r.bp_index).sort()).toEqual([0, 1, 2, 3, 4])
  })
})
