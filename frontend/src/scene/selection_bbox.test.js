import { describe, it, expect } from 'vitest'
import { selectionBBox } from './selection_bbox.js'

const nuc = (strand_id, pos, domain_id = null) => ({ strand_id, domain_id, backbone_position: pos })
const geom = [
  nuc('s1', [0, 0, 0]),
  nuc('s1', [2, 4, 6]),
  nuc('s2', [10, 10, 10]),
]

describe('selectionBBox', () => {
  it('boxes the matched strand by multiSelected strandIds', () => {
    const box = selectionBBox(geom, { strandIds: new Set(['s1']) })
    expect(box.min.toArray()).toEqual([0, 0, 0])
    expect(box.max.toArray()).toEqual([2, 4, 6])
  })
  it('matches the single-selected strand id', () => {
    const box = selectionBBox(geom, { selStrandId: 's2' })
    expect(box.min.toArray()).toEqual([10, 10, 10])
    expect(box.max.toArray()).toEqual([10, 10, 10])
  })
  it('matches by domain id', () => {
    const g = [nuc('s1', [1, 1, 1], 'd1'), nuc('s1', [3, 3, 3], 'd2')]
    const box = selectionBBox(g, { domainIds: new Set(['d2']) })
    expect(box.min.toArray()).toEqual([3, 3, 3])
  })
  it('returns null with no selection or no geometry', () => {
    expect(selectionBBox(geom, {})).toBeNull()
    expect(selectionBBox([], { strandIds: new Set(['s1']) })).toBeNull()
    expect(selectionBBox(geom, { strandIds: new Set(['nope']) })).toBeNull()
  })
})
