import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { selectionBBox, instanceUnionBox } from './selection_bbox.js'

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

const center = (id, c, size) => ({ id, center: new THREE.Vector3(...c), size })

describe('instanceUnionBox', () => {
  it('unions the half-extents of every wanted instance', () => {
    const centers = [
      center('a', [0, 0, 0], { x: 2, y: 2, z: 2 }),   // → [-1,-1,-1]..[1,1,1]
      center('b', [10, 0, 0], { x: 4, y: 2, z: 2 }),  // → [8,-1,-1]..[12,1,1]
    ]
    const box = instanceUnionBox(centers, new Set(['a', 'b']))
    expect(box.min.toArray()).toEqual([-1, -1, -1])
    expect(box.max.toArray()).toEqual([12, 1, 1])
  })

  it('ignores instances not in the wanted set', () => {
    const centers = [
      center('a', [0, 0, 0], { x: 2, y: 2, z: 2 }),
      center('b', [100, 100, 100], { x: 2, y: 2, z: 2 }),
    ]
    const box = instanceUnionBox(centers, new Set(['a']))
    expect(box.min.toArray()).toEqual([-1, -1, -1])
    expect(box.max.toArray()).toEqual([1, 1, 1])
  })

  it('skips sizeless centers (no `size`)', () => {
    const centers = [
      center('a', [0, 0, 0], { x: 2, y: 2, z: 2 }),
      { id: 'b', center: new THREE.Vector3(50, 50, 50) }, // no size → skipped
    ]
    const box = instanceUnionBox(centers, new Set(['a', 'b']))
    expect(box.max.toArray()).toEqual([1, 1, 1])
  })

  it('returns null when nothing matches / inputs empty', () => {
    const centers = [center('a', [0, 0, 0], { x: 2, y: 2, z: 2 })]
    expect(instanceUnionBox(centers, new Set(['nope']))).toBeNull()
    expect(instanceUnionBox(centers, new Set())).toBeNull()
    expect(instanceUnionBox([], new Set(['a']))).toBeNull()
    expect(instanceUnionBox(null, new Set(['a']))).toBeNull()
    expect(instanceUnionBox(centers, null)).toBeNull()
  })

  it('returns null when every matched center is sizeless (union stays empty)', () => {
    const centers = [{ id: 'a', center: new THREE.Vector3(0, 0, 0) }]
    expect(instanceUnionBox(centers, new Set(['a']))).toBeNull()
  })
})
