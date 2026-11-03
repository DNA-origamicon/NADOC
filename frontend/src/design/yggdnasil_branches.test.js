import { it, expect } from 'vitest'
import { enumerateRods } from './yggdnasil.js'
import { buildYggBranches } from './yggdnasil_branches.js'
it('grafts monotonic curvature limbs on shared straight junctions, excluding failed traversal designs', () => {
  const model = buildYggBranches(enumerateRods(), { length: 100 })
  const byId = new Map(model.nodes.map(n => [n.id, n]))
  expect(model.branchCount).toBeGreaterThan(1)
  for (const edge of model.edges.filter(e => e.parameter === 'curvature-counts')) {
    const a = byId.get(edge.from), b = byId.get(edge.to), root = byId.get(b.rootId)
    expect(root.curvature.angleRad).toBe(0)
    expect(root.routing.excluded).toBe(false)
    expect(a.rootId).toBe(b.rootId)
    expect(a.entry).toBe(b.entry)
    expect(a.length).toBe(b.length)
    expect(b.curvature.index).toBe(a.curvature.index + 1)
    expect(b.curvature.angleRad).toBeGreaterThan(a.curvature.angleRad)
    expect(b.curvature.angleDeg % 5).toBe(0)
    expect(b.curvature.angleDeg).toBeLessThanOrEqual(model.catalogs.get(b.entry.id).maxAngleDeg + 1e-8)
    expect(b.curvature.used).toBeLessThanOrEqual(7249)
    expect(b.curvature.eligible).toBe(true)
  }
  for (const node of model.nodes.filter(n => n.routing.excluded)) {
    expect(node.rootId).toBeUndefined()
    expect(model.edges.some(e => e.parameter === 'curvature-counts' && (e.from === node.id || e.to === node.id))).toBe(false)
  }
  expect(new Set(model.nodes.map(n => n.id)).size).toBe(model.nodes.length)
})
it('keeps excluded-only filters free of curvature branches', () => {
  const model = buildYggBranches(enumerateRods(), { length: 100, filter: 'excluded' })
  expect(model.branchCount).toBe(0)
  expect(model.nodes.every(n => !n.curvature)).toBe(true)
})
