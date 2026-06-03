import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import {
  signedAngleFromWorldDelta, movingSideSignForRevolute,
  clampJointValue, gearEndpointSide, rotationDeltaMatrix,
} from './gear_math.js'

describe('clampJointValue', () => {
  it('clamps to [min,max]', () => {
    const j = { min_limit: 0, max_limit: 10 }
    expect(clampJointValue(j, 5)).toBe(5)
    expect(clampJointValue(j, -3)).toBe(0)
    expect(clampJointValue(j, 99)).toBe(10)
  })
  it('passes through when a limit is absent or no joint', () => {
    expect(clampJointValue({ max_limit: 10 }, -50)).toBe(-50)
    expect(clampJointValue({}, 123)).toBe(123)
    expect(clampJointValue(null, 7)).toBe(7)
  })
})

describe('movingSideSignForRevolute', () => {
  const j = { instance_a_id: 'A', instance_b_id: 'B' }
  it('-1 when only a moves, +1 when only b moves', () => {
    expect(movingSideSignForRevolute(j, new Set(['A']))).toBe(-1)
    expect(movingSideSignForRevolute(j, new Set(['B']))).toBe(1)
  })
  it('+1 when both/neither move or args missing', () => {
    expect(movingSideSignForRevolute(j, new Set(['A', 'B']))).toBe(1)
    expect(movingSideSignForRevolute(j, new Set())).toBe(1)
    expect(movingSideSignForRevolute(null, new Set(['A']))).toBe(1)
  })
})

describe('gearEndpointSide', () => {
  const joint = { instance_a_id: 'A', instance_b_id: 'B' }
  it('explicit side wins', () => {
    expect(gearEndpointSide({ endpoint_a_side: 'a' }, 'a', joint)).toBe('a')
    expect(gearEndpointSide({ endpoint_b_side: 'b' }, 'b', joint)).toBe('b')
  })
  it('falls back to instance-id match, else b', () => {
    expect(gearEndpointSide({ endpoint_a_instance_id: 'A' }, 'a', joint)).toBe('a')
    expect(gearEndpointSide({ endpoint_a_instance_id: 'B' }, 'a', joint)).toBe('b')
    expect(gearEndpointSide({}, 'a', joint)).toBe('b')
  })
  it("returns 'b' with no joint", () => {
    expect(gearEndpointSide({ endpoint_a_side: 'a' }, 'a', null)).toBe('b')
  })
})

describe('rotationDeltaMatrix', () => {
  it('rotates 90° about z through the origin', () => {
    const p = new THREE.Vector3(1, 0, 0).applyMatrix4(rotationDeltaMatrix([0, 0, 0], [0, 0, 1], Math.PI / 2))
    expect(p.x).toBeCloseTo(0); expect(p.y).toBeCloseTo(1); expect(p.z).toBeCloseTo(0)
  })
  it('rotates about an axis through a non-origin pivot', () => {
    // point is 1 unit +x of the pivot (2,0,0); a +90° turn about z puts it 1 unit +y of the pivot.
    const p = new THREE.Vector3(3, 0, 0).applyMatrix4(rotationDeltaMatrix([2, 0, 0], [0, 0, 1], Math.PI / 2))
    expect(p.x).toBeCloseTo(2); expect(p.y).toBeCloseTo(1); expect(p.z).toBeCloseTo(0)
  })
  it('defaults to z-axis / origin when given null', () => {
    const p = new THREE.Vector3(1, 0, 0).applyMatrix4(rotationDeltaMatrix(null, null, Math.PI / 2))
    expect(p.y).toBeCloseTo(1)
  })
})

describe('signedAngleFromWorldDelta', () => {
  const z = () => new THREE.Vector3(0, 0, 1)
  it('recovers the signed rotation angle about the axis', () => {
    expect(signedAngleFromWorldDelta(new THREE.Matrix4().makeRotationAxis(z(), 0.7), z())).toBeCloseTo(0.7)
    expect(signedAngleFromWorldDelta(new THREE.Matrix4().makeRotationAxis(z(), -0.5), z())).toBeCloseTo(-0.5)
  })
  it('returns 0 for missing args', () => {
    expect(signedAngleFromWorldDelta(null, z())).toBe(0)
    expect(signedAngleFromWorldDelta(new THREE.Matrix4(), null)).toBe(0)
  })
})
