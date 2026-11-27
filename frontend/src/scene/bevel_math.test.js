import { expect, it } from 'vitest'
import * as THREE from 'three'
import { bevelPlane, bevelMask, nearestBevelBp, bevelAngles } from './bevel_math.js'
const paths = [{ helix_id: 'h', bps: [0, 1, 2, 3], points: [[0, 0, 0], [0, 0, 1], [1, 0, 1], [2, 0, 1]],
  tangents: [[0, 0, 1], [0, 0, 1], [1, 0, 0], [1, 0, 0]], rights: [[1, 0, 0], [1, 0, 0], [0, 0, -1], [0, 0, -1]] }]
const values = { positionBp: 2, angleDeg: 0, directionDeg: 0, trimEnd: 'end' }
it('follows the occupied cornered axis and cuts whole stations by signed distance', () => {
  const frame = bevelPlane(paths, values)
  expect(frame.center.toArray()).toEqual([1, 0, 1]); expect(frame.normal.toArray()).toEqual([1, 0, 0])
  const keep = bevelMask(paths, values)
  expect([0, 1, 2, 3].filter(bp_index => keep({ helix_id: 'h', bp_index }))).toEqual([0, 1, 2])
  expect(keep({ helix_id: 'unselected', bp_index: 9 })).toBe(true)
})
it('snaps face dragging to nearest segment across the corner', () => {
  expect(nearestBevelBp(paths, new THREE.Vector3(1.8, .2, 1))).toBe(3)
  expect(nearestBevelBp(paths, new THREE.Vector3(0, 0, .1))).toBe(0)
})
it('round trips rotation relative to the transported frame', () => {
  const input = { ...values, angleDeg: 35, directionDeg: 220 }
  const frame = bevelPlane(paths, input), angles = bevelAngles(frame.normal, frame)
  expect(angles.angleDeg).toBeCloseTo(35); expect(angles.directionDeg).toBeCloseTo(220)
})
it('refuses empty/no-op material cuts and missing stations', () => {
  expect(() => bevelMask(paths, { ...values, positionBp: 3 })).toThrow(/both sides/)
  expect(() => bevelPlane(paths, { ...values, positionBp: 10 })).toThrow(/occupied/)
})
