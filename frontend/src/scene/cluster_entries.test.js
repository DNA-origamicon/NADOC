import { describe, it, expect } from 'vitest'
import { clusterBackboneEntries, clusterMemberFilter } from './cluster_entries.js'

const entry = (helix_id, strand_id, domain_index) => ({ nuc: { helix_id, strand_id, domain_index } })
const entries = [
  entry('h1', 's1', 0),
  entry('h2', 's1', 1),
  entry('h3', 's2', 0),
]

describe('clusterBackboneEntries', () => {
  it('plain cluster → all entries on its helix_ids', () => {
    const out = clusterBackboneEntries({ helix_ids: ['h1', 'h3'] }, {}, entries)
    expect(out.map(e => e.nuc.helix_id)).toEqual(['h1', 'h3'])
  })

  it('mixed cluster → bridge-domain entries + exclusively-owned helices', () => {
    // bridge domain s1/1 lives on h2, so h2 is NOT exclusive; h1 is exclusive.
    const design = { strands: [{ id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }] }
    const cluster = { helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] }
    const out = clusterBackboneEntries(cluster, design, entries)
    // h1 entry (exclusive) + the s1:1 bridge entry (on h2); the h3 entry excluded.
    expect(out).toEqual([entry('h1', 's1', 0), entry('h2', 's1', 1)])
  })

  it('empty for missing helix_ids or no entries', () => {
    expect(clusterBackboneEntries({ helix_ids: [] }, {}, entries)).toEqual([])
    expect(clusterBackboneEntries({ helix_ids: ['h1'] }, {}, [])).toEqual([])
  })
})

// The predicate behind clusterBackboneEntries. It became a public export when
// three byte-identical copies (here, cluster_gizmo.js, assembly_renderer.js)
// were collapsed into one, so it needs pinning in its own right — in particular
// the null-vs-matches-nothing distinction its five callers branch on.
describe('clusterMemberFilter', () => {
  const nucOf = e => e.nuc

  it('returns null (not an always-false predicate) for a cluster with no helix_ids', () => {
    expect(clusterMemberFilter({ helix_ids: [] }, {})).toBeNull()
    expect(clusterMemberFilter(null, {})).toBeNull()
    expect(clusterMemberFilter(undefined, {})).toBeNull()
  })

  it('plain cluster → membership by helix_id alone', () => {
    const f = clusterMemberFilter({ helix_ids: ['h1', 'h3'] }, {})
    expect(entries.map(nucOf).map(f)).toEqual([true, false, true])
  })

  it('mixed cluster → bridge domains plus exclusively-owned helices', () => {
    const design = { strands: [{ id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }] }
    const cluster = { helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] }
    const f = clusterMemberFilter(cluster, design)
    expect(f({ helix_id: 'h1', strand_id: 's1', domain_index: 0 })).toBe(true)   // exclusive helix
    expect(f({ helix_id: 'h2', strand_id: 's1', domain_index: 1 })).toBe(true)   // the bridge domain
    expect(f({ helix_id: 'h2', strand_id: 's2', domain_index: 0 })).toBe(false)  // h2 is shared, not exclusive
    expect(f({ helix_id: 'h3', strand_id: 's2', domain_index: 0 })).toBe(false)  // outside the cluster
  })

  it('tolerates a design whose strands are missing (unresolvable bridge domain)', () => {
    const cluster = { helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 'gone', domain_index: 0 }] }
    const f = clusterMemberFilter(cluster, {})
    // no bridge helix resolves → every listed helix stays exclusive
    expect(f({ helix_id: 'h1', strand_id: 's1', domain_index: 0 })).toBe(true)
    expect(f({ helix_id: 'h2', strand_id: 's1', domain_index: 0 })).toBe(true)
  })

  it('agrees with clusterBackboneEntries (the wrapper is just a filter over it)', () => {
    const design = { strands: [{ id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }] }
    const cluster = { helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] }
    const f = clusterMemberFilter(cluster, design)
    expect(clusterBackboneEntries(cluster, design, entries)).toEqual(entries.filter(e => f(e.nuc)))
  })
})
