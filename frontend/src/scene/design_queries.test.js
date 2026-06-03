import { describe, it, expect } from 'vitest'
import { surfaceSegments, isExtrudeOverhang, ovhgDomainIds, flexAnchorKey, connIdForBead } from './design_queries.js'

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
