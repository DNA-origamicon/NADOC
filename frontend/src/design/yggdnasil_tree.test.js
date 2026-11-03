import { describe, it, expect } from 'vitest'
import { enumerateRods } from './yggdnasil.js'
import { buildYggTree } from './yggdnasil_tree.js'

const atlas = enumerateRods()
describe('YggDNAsil tree semantics', () => {
  it('holds length, lattice and center fixed across every edge, with no skipped radius shells', () => {
    const tree = buildYggTree(atlas, { length: 100 })
    expect(tree.nodes.length).toBeGreaterThan(10)
    for (const edge of tree.edges) {
      const a = tree.nodes.find(n => n.id === edge.from), b = tree.nodes.find(n => n.id === edge.to)
      expect(a.lattice).toBe(b.lattice); expect(a.center).toBe(b.center)
      expect(a.length).toBe(100); expect(b.length).toBe(100)
      expect(b.index).toBe(a.index + 1)
      expect(b.radiusNm).toBeGreaterThan(a.radiusNm)
      expect(edge.deltaHelices).toBe(b.entry.helices - a.entry.helices)
      expect(a.entry.maxLength).toBeGreaterThanOrEqual(100)
    }
  })
  it('removes edges around filtered nodes without inventing bypass connections', () => {
    const all = buildYggTree(atlas, { length: 21 })
    const kept = buildYggTree(atlas, { length: 21, filter: 'remaining' })
    const original = new Set(all.edges.map(e => `${e.from}/${e.to}`))
    expect(kept.nodes.length).toBeLessThan(all.nodes.length)
    expect(kept.nodes.every(n => !n.routing.excluded)).toBe(true)
    expect(kept.edges.every(e => original.has(`${e.from}/${e.to}`))).toBe(true)
  })
  it('connects 40 → 42 → 44 as separate one-radius steps when those shells exist', () => {
    const entries = [40, 42, 44].map((helices, i) => ({ id: `example-${helices}`, lattice: 'square', helices,
      minLength: 21, maxLength: 150, sources: [{ center: 'Cell', radiusNm: i + 1 }] }))
    const tree = buildYggTree({ entries }, { length: 100 })
    expect(tree.edges.map(e => e.deltaHelices)).toEqual([2, 2])
    expect(tree.edges.map(e => [e.from, e.to])).toEqual([['example-40:Cell', 'example-42:Cell'], ['example-42:Cell', 'example-44:Cell']])
  })
})
