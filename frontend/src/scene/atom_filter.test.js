import { describe, it, expect } from 'vitest'
import { filterAtomData } from './atom_filter.js'

const cache = {
  atoms: [
    { serial: 1, helix_id: 'h1', bp_index: 0 },
    { serial: 2, helix_id: 'h1', bp_index: 1 },
    { serial: 3, helix_id: 'h2', bp_index: 0 },
  ],
  bonds: [[1, 2], [2, 3]],
  element_meta: { C: 6 },
}

describe('filterAtomData', () => {
  it('keeps only atoms whose helix:bp is in the set', () => {
    const { atoms } = filterAtomData(cache, new Set(['h1:0', 'h1:1']), false)
    expect(atoms.map(a => a.serial)).toEqual([1, 2])
  })

  it('omits bonds when withBonds is false', () => {
    expect(filterAtomData(cache, new Set(['h1:0', 'h1:1']), false).bonds).toEqual([])
  })

  it('keeps only bonds whose BOTH endpoints survived', () => {
    // keep atoms 1,2 → bond [1,2] survives, [2,3] drops (3 filtered out).
    expect(filterAtomData(cache, new Set(['h1:0', 'h1:1']), true).bonds).toEqual([[1, 2]])
  })

  it('passes element_meta through and tolerates an empty cache', () => {
    expect(filterAtomData(cache, new Set(), false).element_meta).toEqual({ C: 6 })
    expect(filterAtomData(undefined, new Set(['x']), true)).toEqual({ atoms: [], bonds: [], element_meta: undefined })
  })
})
