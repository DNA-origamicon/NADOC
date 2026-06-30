import { describe, it, expect } from 'vitest'
import { surfaceSegments, isExtrudeOverhang, ovhgDomainIds, ovhgBinderDomainIds, flexAnchorKey, connIdForBead, flexibleRunForBead, assembleOverhangSequence, overhangHasSequenceOverride } from './design_queries.js'

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
