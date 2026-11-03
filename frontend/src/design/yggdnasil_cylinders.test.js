import { it, expect } from 'vitest'
import { enumerateRods, CENTERS } from './yggdnasil.js'
import { enumerateCylinders, closedCylinderWall } from './yggdnasil_cylinders.js'
import { buildCylinderTree } from './yggdnasil_cylinder_tree.js'
import { routingScreen, routingTotals } from './yggdnasil_routing.js'
import report from './yggdnasil_cylinder_routing.json'
const atlas = enumerateCylinders()
it('enumerates budgeted closed hollow walls beyond the solid outer-radius limit', () => {
  expect(atlas.entries.length).toBe(748)
  expect(new Set(atlas.entries.map(e => e.canonical)).size).toBe(atlas.entries.length)
  const solids = enumerateRods({ minLength: 100 })
  const solidLimit = Math.max(...solids.entries.flatMap(e => e.sources.map(s => s.radiusNm)))
  expect(atlas.entries.some(e => e.sources.some(s => s.outerRadiusNm > solidLimit))).toBe(true)
  for (const entry of atlas.entries) {
    expect(entry.helices * 100).toBeLessThanOrEqual(7249)
    for (const source of entry.sources) {
      const [, cx, cy] = CENTERS[entry.lattice].find(c => c[0] === source.center)
      for (const p of entry.points) {
        const r2 = 4 * ((p.x - cx) ** 2 + (p.y - cy) ** 2)
        expect(r2).toBeGreaterThan(source.innerShell + 1e-7)
        expect(r2).toBeLessThanOrEqual(source.outerShell + 1e-7)
      }
    }
    expect(routingScreen(entry).status).not.toBe('not_screened')
  }
  const t = routingTotals(atlas.entries)
  expect(t.path_found).toBe(166); expect(t.excluded).toBe(560); expect(t.unresolved).toBe(22)
  expect(report.records.length).toBe(atlas.entries.length)
})
it('rejects an open wall and an empty interior', () => {
  const point = (row, col) => ({ row, col, x: col, y: row })
  const removed = [point(0, 0)], wall = []
  for (let r = -1; r <= 1; r++) for (let c = -1; c <= 1; c++) if (r || c) wall.push(point(r, c))
  expect(closedCylinderWall('square', wall, removed)).toBe(true)
  expect(closedCylinderWall('square', wall.filter(p => p.row !== 0 || p.col !== 1), removed)).toBe(false)
  expect(closedCylinderWall('square', wall, [])).toBe(false)
})
it('draws only straight non-excluded cylinders and preserves inner-shell adjacency', () => {
  const tree = buildCylinderTree(atlas), nodes = new Map(tree.nodes.map(n => [n.id, n]))
  expect(tree.nodes.length).toBeGreaterThan(0)
  for (const n of tree.nodes) { expect(n.curvature).toBeUndefined(); expect(n.routing.excluded).toBe(false) }
  for (const e of tree.edges) {
    const a = nodes.get(e.from), b = nodes.get(e.to)
    expect(e.parameter).toBe('inner-radius'); expect(a.outerRadiusNm).toBe(b.outerRadiusNm)
    expect(a.length).toBe(b.length); expect(a.center).toBe(b.center)
    expect(b.index).toBe(a.index + 1); expect(b.innerRadiusNm).toBeGreaterThan(a.innerRadiusNm)
    expect(b.entry.helices).toBeLessThan(a.entry.helices)
  }
  expect(buildCylinderTree(atlas, { filter: 'excluded' }).nodes).toHaveLength(0)
  expect(buildCylinderTree(atlas, { filter: 'unresolved' }).nodes.every(n => n.routing.status === 'unresolved')).toBe(true)
  expect(enumerateCylinders({ length: 7249 }).entries).toHaveLength(0)
})

it('labels larger unaudited walls unresolved instead of borrowing a solid traversal', () => {
  const larger = enumerateCylinders({ length: 90 })
  const entry = larger.entries.find(e => e.helices > 72 && e.points.filter(p => (p.row + p.col) % 2 === 0).length * 2 === e.helices)
  expect(entry).toBeDefined()
  expect(routingScreen(entry).status).toBe('unresolved')
  expect(routingScreen(entry).label).toContain('not yet screened')
  expect(routingScreen(entry).path).toBeNull()
})
