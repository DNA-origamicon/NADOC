import { expect, it } from 'vitest'
import { latticeCellEdges, createLatticeEdgeCache } from './hull_lattice_edges.js'

it('preserves directed loop order and the existing quantization, including closing edge', () => {
  const a = { x: -1, z: 0 }, b = { x: 1, z: 0 }, c = { x: 1, z: 1.000000001 }
  const edges = latticeCellEdges([a, b, c])
  expect(edges.map(e => e.key)).toEqual(['-10000000,0>10000000,0', '10000000,0>10000000,10000000', '10000000,10000000>-10000000,0'])
  expect(edges[2].b).toBe(a)
  expect(edges[0].reverse).toBe('10000000,0>-10000000,0')
})

it('reuses immutable cell edges only within their hull build', () => {
  let calls = 0
  const cell = { row: 0 }, polygon = () => { calls++; return [{ x: cell.row, z: 0 }, { x: 1, z: 1 }, { x: -1, z: 1 }] }
  const first = createLatticeEdgeCache(polygon)
  expect(first(cell)).toBe(first(cell)); expect(calls).toBe(1)
  cell.row = 4
  const second = createLatticeEdgeCache(polygon)
  expect(second(cell)[0].a.x).toBe(4)
  expect(first(cell)[0].a.x).toBe(0)
})
