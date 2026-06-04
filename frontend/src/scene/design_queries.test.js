import { describe, it, expect } from 'vitest'
import { surfaceSegments, isExtrudeOverhang, ovhgDomainIds, flexAnchorKey, connIdForBead, flexibleRunForBead } from './design_queries.js'

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
