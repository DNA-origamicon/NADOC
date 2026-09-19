import { describe, it, expect } from 'vitest'
import { anchorFromPoints, describeTarget, matchTargetEntries, unresolvedBaseKeys } from './annotation_targets.js'

const nuc = (strand_id, helix_id, bp_index, direction = 'FORWARD', domain_index = 0) => ({ strand_id, helix_id, bp_index, direction, domain_index })
const entry = (n, x = 0) => ({ nuc: n, pos: { x, y: 0, z: 0 } })
const entries = [
  entry(nuc('s1', 'h0', 0), 0), entry(nuc('s1', 'h0', 1), 1), entry(nuc('s1', 'h1', 1, 'REVERSE', 1), 2),
  entry(nuc('s2', 'h1', 5, 'FORWARD', 0), 3), entry(nuc('s2', '__ext_e1', 0), 4),
]
const design = {
  strands: [{ id: 's1', name: 'Scaffold' }, { id: 's2' }],
  cluster_transforms: [{ id: 'c1', name: 'Arm', helix_ids: ['h1'], domain_ids: [] }, { id: 'c2', name: 'Dom', domain_ids: [{ strand_id: 's1', domain_index: 1 }] }],
  crossovers: [{ id: 'x1', half_a: { helix_id: 'h0', index: 1, strand: 'FORWARD' }, half_b: { helix_id: 'h1', index: 1, strand: 'REVERSE' } }],
  forced_ligations: [{ id: 'f1', three_prime_helix_id: 'h0', three_prime_bp: 0, three_prime_direction: 'FORWARD', five_prime_helix_id: 'h1', five_prime_bp: 5, five_prime_direction: 'FORWARD' }],
  overhangs: [{ id: 'o1', strand_id: 's2' }],
}
const pick = refs => matchTargetEntries(refs, design, entries).map(e => entries.indexOf(e))

describe('matchTargetEntries', () => {
  it('matches strand, domain, base/end', () => {
    expect(pick([{ kind: 'strand', id: 's1' }])).toEqual([0, 1, 2])
    expect(pick([{ kind: 'domain', strandId: 's1', domainIndex: 1 }])).toEqual([2])
    expect(pick([{ kind: 'base', key: 'h0:1:FORWARD' }])).toEqual([1])
    expect(pick([{ kind: 'end', key: 'h1:5:FORWARD' }])).toEqual([3])
  })
  it('matches a helix-level cluster by helix and a domain-level cluster by domain', () => {
    expect(pick([{ kind: 'cluster', id: 'c1' }])).toEqual([2, 3])
    expect(pick([{ kind: 'cluster', id: 'c2' }])).toEqual([2])
  })
  it('matches crossover halves, forced-ligation ends, bonds and extensions', () => {
    expect(pick([{ kind: 'crossover', id: 'x1', subtype: 'crossover' }])).toEqual([1, 2])
    expect(pick([{ kind: 'crossover', id: 'f1', subtype: 'forced_ligation' }])).toEqual([0, 3])
    expect(pick([{ kind: 'bond', fromKey: 'h0:0:FORWARD', toKey: 'h0:1:FORWARD' }])).toEqual([0, 1])
    expect(pick([{ kind: 'extension', id: 'e1' }])).toEqual([4])
  })
  it('returns nothing for empty refs, unknown ids and unsupported kinds', () => {
    expect(pick([])).toEqual([])
    expect(pick([{ kind: 'strand', id: 'nope' }])).toEqual([])
    expect(pick([{ kind: 'protein', id: 'p' }])).toEqual([])
  })
})

describe('unresolvedBaseKeys', () => {
  it('reports base keys the backbone entries did not supply', () => {
    const refs = [{ kind: 'base', key: 'h0:0:FORWARD' }, { kind: 'base', key: '__xb__:x9:0' }]
    expect(unresolvedBaseKeys(refs, matchTargetEntries(refs, design, entries))).toEqual(['__xb__:x9:0'])
  })
})

describe('anchorFromPoints', () => {
  it('is null for none, the point for one, and the member nearest the centroid otherwise', () => {
    expect(anchorFromPoints([])).toBeNull()
    expect(anchorFromPoints([{ x: 1, y: 2, z: 3 }])).toEqual({ x: 1, y: 2, z: 3 })
    expect(anchorFromPoints([{ x: 0, y: 0, z: 0 }, { x: 4, y: 0, z: 0 }, { x: 5, y: 0, z: 0 }])).toEqual({ x: 4, y: 0, z: 0 })
  })
})

describe('describeTarget', () => {
  it('summarises one and many refs', () => {
    expect(describeTarget([], design)).toBe('No target')
    expect(describeTarget([{ kind: 'strand', id: 's1' }], design)).toBe('Strand · Scaffold')
    expect(describeTarget([{ kind: 'domain', strandId: 's1', domainIndex: 1 }], design)).toBe('Domain 2 · Scaffold')
    expect(describeTarget([{ kind: 'nanoparticle', id: 'n1' }], { nanoparticles: [{ id: 'n1', kind: 'gold_nanosphere', diameter_nm: 20 }] })).toBe('Gold nanosphere · 20 nm')
    expect(describeTarget([{ kind: 'strand', id: 's1' }, { kind: 'strand', id: 's2' }, { kind: 'base', key: 'h0:0:FORWARD' }], design))
      .toBe('3 items · 2 strands, 1 base')
  })
})
