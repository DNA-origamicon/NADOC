import { expect, it } from 'vitest'
import { boxSweptSections, createHullSweepFrame } from './hull_sweep.js'

const design = { helices: [{ id: 'a', bp_start: 3 }, { id: 'b', bp_start: 3 }, { id: 'c', bp_start: 3 }] }
const axes = Object.fromEntries(design.helices.map((h, j) => [h.id, {
  samples: Array.from({ length: 18 - j }, (_, i) => [j * 2 + Math.sin(i / 8), Math.cos(i / 8) * 8, i * 2]),
}]))
const plain = sections => sections?.map(s => ({ center: s.center.toArray(), U: s.U.toArray(),
  V: s.V.toArray(), tangent: s.tangent.toArray(), corners: s.corners }))

it('reuses a common spine with exact box frames for changing ranges, member sets, and sample lengths', () => {
  const ids = ['a', 'b', 'c'], context = createHullSweepFrame(design, axes, ids)
  // Long→short→long exercises the endpoint tangent and transport anchor rules.
  for (const [lo, hi, members] of [[3, 99, ['b']], [17, 38, ['a', 'c']], [31, 115, ['a']], [3, 10, ids]]) {
    const expected = boxSweptSections(design, axes, members, lo, hi, 2.5, 3.5, ids)
    const actual = boxSweptSections(design, axes, members, lo, hi, 2.5, 3.5, ids, context)
    expect(plain(actual)).toEqual(plain(expected))
  }
})

it('preserves empty and too-short ranges and isolates separate axes snapshots', () => {
  expect(boxSweptSections(design, {}, ['a'], 0, 30, 2, 2)).toBeNull()
  const first = createHullSweepFrame(design, axes, ['a'])
  expect(boxSweptSections(design, axes, ['a'], 5, 5, 2, 2, ['a'], first)).toBeNull()
  const moved = { a: { samples: axes.a.samples.map(p => [p[0] + 100, p[1], p[2]]) } }
  const second = createHullSweepFrame(design, moved, ['a'])
  expect(second.centersThrough(3)[3].x - first.centersThrough(3)[3].x).toBeCloseTo(100)
  expect(first.centersThrough(1)).toHaveLength(2)
})
