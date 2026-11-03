import { it, expect } from 'vitest'
import { enumerateRods } from './yggdnasil.js'
import { curvatureCatalog, curvatureSamples, curvatureTree, curvatureWindow, cellAllocation } from './yggdnasil_curvature.js'
const atlas = enumerateRods()
const square = atlas.entries.find(e => e.lattice === 'square' && e.helices === 4)
const thick = atlas.entries.find(e => e.lattice === 'square' && e.helices > 100)

it('caps the total turn at 360° and includes a complete-circle representative', () => {
  const c = curvatureCatalog(square, 100)
  expect(c.maxAngleDeg).toBeCloseTo(360)
  expect(c.states.at(-1).angleDeg).toBeCloseTo(360)
  expect(c.states.every(s => s.angleDeg <= 360 + 1e-8)).toBe(true)
  expect(new Set(c.states.map(s => s.key)).size).toBe(c.states.length)
  expect(c.states[0].loops).toBe(0)
  expect(c.states[0].skips).toBe(9) // native staggered 48-bp square compensation: 3+2+2+2
  expect(c.states[0].angleDeg).toBe(0)
})
it('limits a thick short rod using the same local density as Sweep', () => {
  const c = curvatureCatalog(thick, 30)
  expect(c.maxAngleDeg).toBeLessThan(360)
  expect(c.maxAngleDeg * Math.PI / 180).toBeCloseTo(3 * 30 * 0.334 / (7 * c.frame.extent))
  expect(c.states.every(s => s.maxDeltaPerCell <= 3 + 1e-7)).toBe(true)
})
it('accounts for insertions and deletions separately, with exact count conservation per cell', () => {
  for (const entry of [square, atlas.entries.find(e => e.lattice === 'honeycomb' && e.helices === 6)]) {
    const c = curvatureCatalog(entry, 100)
    for (const state of c.states) {
      const rows = cellAllocation(c, state)
      expect(rows.reduce((n, r) => n + r.loops, 0)).toBe(state.loops)
      expect(rows.reduce((n, r) => n + r.skips, 0)).toBe(state.skips)
      expect(rows.every(r => r.loops + r.skips <= 3 && r.loops + r.skips <= r.length)).toBe(true)
      expect(state.used).toBe(entry.helices * 100 + state.loops - state.skips)
      expect(state.used + state.remainder).toBe(7249)
    }
  }
})
it('allows deletion-adjusted lengths and prunes over-budget count classes', () => {
  const adjusted = curvatureCatalog(square, 1840)
  expect(square.helices * 1840).toBeGreaterThan(7249)
  expect(adjusted.states.length).toBeGreaterThan(0)
  expect(adjusted.states.every(s => s.used <= 7249)).toBe(true)
  expect(curvatureCatalog(square, 2000).states).toHaveLength(0)
  expect(curvatureCatalog(square, 100, { reserve: 7248 }).states).toHaveLength(0)
})
it('keeps curved branches at one footprint/length and windows without inventing edges', () => {
  const c = curvatureCatalog(square, 1840), tree = curvatureTree(c)
  expect(tree.nodes.every(n => n.entry === square && n.length === 1840)).toBe(true)
  expect(tree.edges.every(e => e.parameter === 'curvature-counts')).toBe(true)
  const window = curvatureWindow(tree, tree.nodes.at(-1).id, 5)
  expect(window.nodes.length).toBeLessThanOrEqual(5)
  expect(window.nodes.at(-1).id).toBe(tree.nodes.at(-1).id)
  const original = new Set(tree.edges.map(e => `${e.from}/${e.to}`))
  expect(window.edges.every(e => original.has(`${e.from}/${e.to}`))).toBe(true)
})
it('does not create curvature from a single neutral-axis helix', () => {
  const one = atlas.entries.find(e => e.lattice === 'honeycomb' && e.helices === 1)
  const c = curvatureCatalog(one, 100)
  expect(c.states).toHaveLength(1); expect(c.states[0].angleDeg).toBe(0)
})

it('prunes to a five-degree grid without exceeding limits or duplicating count classes', () => {
  for (const [entry, length] of [[square, 100], [thick, 30]]) {
    const raw = curvatureCatalog(entry, length), c = curvatureSamples(raw)
    expect(c.states[0].angleDeg).toBe(0)
    expect(c.states.every(s => s.angleDeg % 5 === 0 && s.angleDeg <= c.maxAngleDeg + 1e-8)).toBe(true)
    expect(c.states.length).toBeLessThanOrEqual(raw.states.length)
    expect(new Set(c.states.map(s => s.key)).size).toBe(c.states.length)
    expect(c.maxSampleAngleDeg).toBe(Math.floor(c.maxAngleDeg / 5) * 5)
    for (const state of c.states) {
      const rows = cellAllocation(c, state)
      expect(rows.reduce((n, r) => n + r.loops, 0)).toBe(state.loops)
      expect(rows.reduce((n, r) => n + r.skips, 0)).toBe(state.skips)
      expect(rows.every(r => r.loops + r.skips <= 3)).toBe(true)
    }
  }
  expect(curvatureSamples(curvatureCatalog(square, 100)).states.at(-1).angleDeg).toBe(360)
  expect(curvatureSamples(curvatureCatalog(square, 2000)).states).toHaveLength(0)
})
