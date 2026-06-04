import { describe, it, expect } from 'vitest'
import { flexTetherConnections } from './flex_tethers.js'

// design lets flexAnchorKey resolve "helix:bp:dir" from {strand_id, domain_index, bp_index, direction}.
const design = { strands: [{ id: 's1', domains: [{ helix_id: 'hA' }, { helix_id: 'hB' }] }] }
const anc = (domain_index, bp_index) => ({ strand_id: 's1', domain_index, bp_index, direction: 'FORWARD' })

describe('flexTetherConnections', () => {
  it('returns moving/fixed keys for connections touching the moving cluster', () => {
    const conns = [{ cluster_a_id: 'cMove', cluster_b_id: 'cFix', anchor_a: anc(0, 1), anchor_b: anc(1, 2), contour_length_nm: 5 }]
    expect(flexTetherConnections(conns, 'cMove', design)).toEqual([
      { movingKey: 'hA:1:FORWARD', fixedKey: 'hB:2:FORWARD', contour: 5 },
    ])
  })
  it('orients moving=the anchor on the moving cluster when it is side B', () => {
    const conns = [{ cluster_a_id: 'cFix', cluster_b_id: 'cMove', anchor_a: anc(0, 1), anchor_b: anc(1, 2), contour_length_nm: 7 }]
    const [t] = flexTetherConnections(conns, 'cMove', design)
    expect(t.movingKey).toBe('hB:2:FORWARD') // anchor_b is on cMove
    expect(t.fixedKey).toBe('hA:1:FORWARD')
  })
  it('skips connections not touching the cluster, and unresolvable anchors', () => {
    expect(flexTetherConnections([{ cluster_a_id: 'x', cluster_b_id: 'y', anchor_a: anc(0, 1), anchor_b: anc(1, 2) }], 'cMove', design)).toEqual([])
    const bad = [{ cluster_a_id: 'cMove', cluster_b_id: 'cFix', anchor_a: anc(9, 1), anchor_b: anc(1, 2) }] // domain 9 missing
    expect(flexTetherConnections(bad, 'cMove', design)).toEqual([])
  })
  it('tolerates null conns', () => {
    expect(flexTetherConnections(null, 'cMove', design)).toEqual([])
  })
})
