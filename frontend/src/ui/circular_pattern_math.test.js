import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { clusterLattice, latticeAligned, latticePoint, snapToLattice, patternAngles } from './circular_pattern_math.js'

function fixture(type = 'SQUARE') {
  const cluster = { id: 'c', helix_ids: ['h'], rotation: [0, 0, 0, 1] }
  return {
    state: { currentDesign: { lattice_type: type, cluster_transforms: [cluster], helices: [{ id: 'h', grid_pos: [0, 0], axis_start: { x: 10, y: 20, z: 0 }, axis_end: { x: 10, y: 20, z: 30 } }] }, currentHelixAxes: { h: { start: [10, 20, 0], end: [10, 20, 30] } } },
    target: { cluster, center: [11, 21, 15] },
  }
}
it('preserves lattice registration relative to a non-lattice centroid and drag depth', () => {
  const { state, target } = fixture()
  const frame = clusterLattice(state, target)
  expect(snapToLattice(frame, [.1, .1, 7])).toEqual([-1, -1, 7])
  expect(latticeAligned(frame, [0, 0, -2])).toBe(true)
  expect(latticeAligned(frame, [1, 0, 1])).toBe(false)
  expect(latticeAligned(frame, [0, 0, 0])).toBe(false)
})
it('snaps to actual staggered honeycomb sites, including negative cells', () => {
  const { state, target } = fixture('HONEYCOMB')
  const frame = clusterLattice(state, target)
  for (const [row, col] of [[0, 1], [-1, 0], [-2, -1]]) {
    const site = latticePoint(frame, row, col, [0, 0, 4])
    const near = site.clone().add(new THREE.Vector3(.2, -.1, 0))
    expect(snapToLattice(frame, near.toArray())).toEqual(site.toArray())
  }
})
it('follows rigid cluster rotations and translations instead of a world XY grid', () => {
  const { state, target } = fixture()
  const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2)
  target.cluster.rotation = q.toArray()
  state.currentHelixAxes.h = { start: [5, 20, -10], end: [35, 20, -10] }
  target.center = [20, 20, -10]
  const frame = clusterLattice(state, target)
  expect(latticeAligned(frame, [1, 0, 0])).toBe(true)
  expect(latticeAligned(frame, [0, 0, 1])).toBe(false)
  const snapped = snapToLattice(frame, [8, 2.1, 2.1])
  expect(snapped[0]).toBeCloseTo(8)
  expect(snapped[1]).toBeCloseTo(2.25)
  expect(snapped[2]).toBeCloseTo(2.25)
})
it('declines inconsistent, curved, or missing lattice data', () => {
  const { state, target } = fixture()
  state.currentHelixAxes.h.samples = [[10, 20, 0], [12, 20, 15], [10, 20, 30]]
  expect(clusterLattice(state, target)).toBeNull()
  delete state.currentHelixAxes.h.samples
  state.currentDesign.helices[0].grid_pos = null
  expect(clusterLattice(state, target)).toBeNull()
})
describe('circular instance spacing', () => {
  it('counts the original and never duplicates the 360 degree endpoint', () => {
    expect(patternAngles(4, 360)).toEqual([0, Math.PI / 2, Math.PI, 3 * Math.PI / 2])
    expect(patternAngles(3, 180)).toEqual([0, Math.PI / 2, Math.PI])
    expect(patternAngles(1, 360)).toEqual([0])
  })
  it('rejects invalid counts and sweeps', () => {
    for (const [n, a] of [[0, 360], [2.5, 360], [129, 360], [6, 0], [6, NaN], [6, 361]]) expect(patternAngles(n, a)).toBeNull()
  })
})
