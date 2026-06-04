import { describe, it, expect } from 'vitest'
import { clusterBackboneEntries } from './cluster_entries.js'

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
