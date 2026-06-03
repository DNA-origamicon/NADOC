import { describe, it, expect } from 'vitest'
import { intersectCoverage, findHamiltonianPath } from './scaffold_coverage.js'

const adj = (obj) => new Map(Object.entries(obj).map(([k, v]) => [k, new Set(v)]))

// A returned path is valid iff it covers every id exactly once and every
// consecutive pair is adjacent.
function isValidPath(path, ids, adjMap) {
  if (!path || path.length !== ids.length) return false
  if (new Set(path).size !== ids.length) return false
  if (!path.every(id => ids.includes(id))) return false
  for (let i = 0; i < path.length - 1; i++) {
    if (!adjMap.get(path[i]).has(path[i + 1])) return false
  }
  return true
}

describe('intersectCoverage', () => {
  it('returns [] for non-overlapping intervals', () => {
    expect(intersectCoverage([{ lo: 0, hi: 5 }], [{ lo: 10, hi: 20 }])).toEqual([])
  })

  it('returns the overlapping sub-interval', () => {
    expect(intersectCoverage([{ lo: 0, hi: 10 }], [{ lo: 5, hi: 20 }])).toEqual([{ lo: 5, hi: 10 }])
  })

  it('includes single-point touches (lo === hi)', () => {
    expect(intersectCoverage([{ lo: 0, hi: 5 }], [{ lo: 5, hi: 9 }])).toEqual([{ lo: 5, hi: 5 }])
  })

  it('produces every pairwise overlap across multiple intervals', () => {
    const a = [{ lo: 0, hi: 4 }, { lo: 10, hi: 14 }]
    const b = [{ lo: 2, hi: 11 }]
    expect(intersectCoverage(a, b)).toEqual([{ lo: 2, hi: 4 }, { lo: 10, hi: 11 }])
  })

  it('returns [] when either list is empty', () => {
    expect(intersectCoverage([], [{ lo: 0, hi: 5 }])).toEqual([])
    expect(intersectCoverage([{ lo: 0, hi: 5 }], [])).toEqual([])
  })
})

describe('findHamiltonianPath', () => {
  it('finds a path through a simple chain', () => {
    const ids = ['1', '2', '3', '4']
    const g = adj({ 1: ['2'], 2: ['1', '3'], 3: ['2', '4'], 4: ['3'] })
    const path = findHamiltonianPath(ids, g)
    expect(isValidPath(path, ids, g)).toBe(true)
  })

  it('returns a single-node path for one node', () => {
    const g = adj({ 1: [] })
    expect(findHamiltonianPath(['1'], g)).toEqual(['1'])
  })

  it('returns null when no Hamiltonian path exists (star graph)', () => {
    const ids = ['C', 'L1', 'L2', 'L3']
    const g = adj({ C: ['L1', 'L2', 'L3'], L1: ['C'], L2: ['C'], L3: ['C'] })
    expect(findHamiltonianPath(ids, g)).toBeNull()
  })

  it('honors startFrom when a path from it exists', () => {
    const ids = ['1', '2', '3']
    const g = adj({ 1: ['2', '3'], 2: ['1', '3'], 3: ['1', '2'] }) // K3
    const path = findHamiltonianPath(ids, g, '2')
    expect(isValidPath(path, ids, g)).toBe(true)
    expect(path[0]).toBe('2')
  })
})
