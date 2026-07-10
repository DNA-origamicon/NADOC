import { describe, expect, it } from 'vitest'

import {
  clusterClosure,
  describeCopy,
  footprintForClusters,
  pasteGridDelta,
  pasteParityCandidates,
  pastePreservesPhase,
  planeOfHelixId,
  unsupportedCopyReason,
} from './cluster_copy_logic.js'

const cluster = (id, helix_ids, parent_cluster_id = null) => ({ id, helix_ids, parent_cluster_id })
const helix = (id, row, col) => ({ id, grid_pos: [row, col] })

describe('pastePreservesPhase', () => {
  it('accepts an even-parity shift', () => {
    expect(pastePreservesPhase([0, 0], { row: 0, col: 2 })).toBe(true)
    expect(pastePreservesPhase([0, 0], { row: 1, col: 1 })).toBe(true)
    expect(pastePreservesPhase([1, 2], { row: 3, col: 2 })).toBe(true)
  })

  it('rejects an odd-parity shift', () => {
    expect(pastePreservesPhase([0, 0], { row: 0, col: 1 })).toBe(false)
    expect(pastePreservesPhase([0, 0], { row: 1, col: 0 })).toBe(false)
  })

  it('handles negative cells (bp/lattice coords are signed)', () => {
    expect(pastePreservesPhase([0, 0], { row: -1, col: -1 })).toBe(true)
    expect(pastePreservesPhase([0, 0], { row: -1, col: 0 })).toBe(false)
  })

  it('is independent of lattice type — square polarity is (row+col)%2 too', () => {
    // Regression pin: placementPreservesShape() returns true for ANY square shift.
    // A cluster paste grafts helices verbatim, so it must not.
    expect(pastePreservesPhase([0, 0], { row: 0, col: 1 })).toBe(false)
  })
})

describe('pasteParityCandidates', () => {
  it('returns the raw cell alone when parity already matches', () => {
    expect(pasteParityCandidates({ row: 0, col: 2 }, [0, 0])).toEqual([[0, 2]])
  })

  it('returns the four edge neighbours when parity is wrong', () => {
    const cands = pasteParityCandidates({ row: 0, col: 1 }, [0, 0])
    expect(cands).toHaveLength(4)
    for (const [r, c] of cands) expect(pastePreservesPhase([0, 0], { row: r, col: c })).toBe(true)
  })
})

describe('pasteGridDelta', () => {
  it('computes the shift from anchor to hover', () => {
    expect(pasteGridDelta([1, 2], { row: 1, col: 6 })).toEqual([0, 4])
    expect(pasteGridDelta([3, 3], { row: 1, col: 1 })).toEqual([-2, -2])
  })
})

describe('clusterClosure', () => {
  const clusters = [
    cluster('parent', ['h1']),
    cluster('child', ['h1'], 'parent'),
    cluster('lonely', ['h2']),
  ]

  it('pulls in the parent when a child is selected', () => {
    const { closureIds, addedIds } = clusterClosure(['child'], clusters)
    expect(new Set(closureIds)).toEqual(new Set(['parent', 'child']))
    expect(addedIds).toEqual(['parent'])
  })

  it('pulls in the child when the parent is selected', () => {
    const { closureIds, addedIds } = clusterClosure(['parent'], clusters)
    expect(new Set(closureIds)).toEqual(new Set(['parent', 'child']))
    expect(addedIds).toEqual(['child'])
  })

  it('reports nothing added when the selection is already closed', () => {
    expect(clusterClosure(['parent', 'child'], clusters).addedIds).toEqual([])
  })

  it('leaves unrelated clusters out', () => {
    expect(clusterClosure(['lonely'], clusters).closureIds).toEqual(['lonely'])
  })

  it('is transitive through a grandparent chain', () => {
    const chain = [cluster('a', ['h']), cluster('b', ['h'], 'a'), cluster('c', ['h'], 'b')]
    expect(new Set(clusterClosure(['c'], chain).closureIds)).toEqual(new Set(['a', 'b', 'c']))
  })

  it('returns empty for an unknown id', () => {
    expect(clusterClosure(['nope'], clusters)).toEqual({ closureIds: [], addedIds: [] })
  })

  it('returns closure in design order, not selection order', () => {
    expect(clusterClosure(['child', 'parent'], clusters).closureIds).toEqual(['parent', 'child'])
  })
})

describe('planeOfHelixId', () => {
  it('reads the plane out of the id', () => {
    expect(planeOfHelixId('h_XY_0_0')).toBe('XY')
    expect(planeOfHelixId('h_YZ_3_-2')).toBe('YZ')
  })

  it('returns null for a non-lattice id', () => {
    expect(planeOfHelixId('some-uuid')).toBeNull()
    expect(planeOfHelixId(undefined)).toBeNull()
  })
})

describe('footprintForClusters', () => {
  const design = {
    lattice_type: 'HONEYCOMB',
    helices: [helix('h_XY_1_1', 1, 1), helix('h_XY_0_2', 0, 2), helix('h_XY_5_5', 5, 5)],
    cluster_transforms: [cluster('cA', ['h_XY_1_1', 'h_XY_0_2']), cluster('cB', ['h_XY_5_5'])],
  }

  it('collects the cells of the selected clusters only', () => {
    const fp = footprintForClusters(['cA'], design)
    expect(fp.cells).toHaveLength(2)
    expect(new Set(fp.cells.map(String))).toEqual(new Set(['1,1', '0,2']))
    expect(fp.helixIds).toHaveLength(2)
  })

  it('anchors on min row then min col', () => {
    expect(footprintForClusters(['cA'], design).anchorCell).toEqual([0, 2])
  })

  it('reads plane and lattice type', () => {
    const fp = footprintForClusters(['cA'], design)
    expect(fp.plane).toBe('XY')
    expect(fp.latticeType).toBe('HONEYCOMB')
  })

  it('unions across multiple clusters', () => {
    expect(footprintForClusters(['cA', 'cB'], design).cells).toHaveLength(3)
  })

  it('returns null when the clusters have no helices', () => {
    expect(footprintForClusters(['nope'], design)).toBeNull()
  })

  it('returns null when helices carry no grid_pos', () => {
    const d = { helices: [{ id: 'x' }], cluster_transforms: [cluster('c', ['x'])] }
    expect(footprintForClusters(['c'], d)).toBeNull()
  })
})

describe('unsupportedCopyReason', () => {
  const base = { overhangs: [], extensions: [], strands: [] }

  it('allows a plain cluster', () => {
    expect(unsupportedCopyReason(['h1'], base)).toBeNull()
  })

  it('refuses an overhang on a copied helix', () => {
    const d = { ...base, overhangs: [{ id: 'o1', helix_id: 'h1' }] }
    expect(unsupportedCopyReason(['h1'], d)).toMatch(/1 overhang\./)
  })

  it('ignores an overhang on a helix outside the copy', () => {
    const d = { ...base, overhangs: [{ id: 'o1', helix_id: 'hOther' }] }
    expect(unsupportedCopyReason(['h1'], d)).toBeNull()
  })

  it('pluralises the overhang count', () => {
    const d = { ...base, overhangs: [{ helix_id: 'h1' }, { helix_id: 'h1' }] }
    expect(unsupportedCopyReason(['h1'], d)).toMatch(/2 overhangs/)
  })

  it('refuses an extension on a strand touching a copied helix', () => {
    const d = {
      ...base,
      strands: [{ id: 's1', domains: [{ helix_id: 'h1' }] }],
      extensions: [{ id: 'e1', strand_id: 's1' }],
    }
    expect(unsupportedCopyReason(['h1'], d)).toMatch(/1 strand extension\./)
  })

  it('ignores an extension on a strand outside the copy', () => {
    const d = {
      ...base,
      strands: [{ id: 's1', domains: [{ helix_id: 'hOther' }] }],
      extensions: [{ id: 'e1', strand_id: 's1' }],
    }
    expect(unsupportedCopyReason(['h1'], d)).toBeNull()
  })

  it('tolerates a design missing the optional lists', () => {
    expect(unsupportedCopyReason(['h1'], {})).toBeNull()
  })
})

describe('describeCopy', () => {
  it('describes a plain copy', () => {
    expect(describeCopy(['a'], [], 4)).toBe('Copied 1 cluster (4 helices)')
  })

  it('mentions auto-added linked clusters', () => {
    expect(describeCopy(['a', 'b'], ['b'], 6)).toBe(
      'Copied 2 clusters (6 helices) — pulled in 1 linked cluster'
    )
  })
})
