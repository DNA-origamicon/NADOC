import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { quatToEulerDeg, eulerDegToQuat, extractJointAngleDeg, posEulerFromMatrix } from './rotation_math.js'

// Quaternion (as {x,y,z,w}) for `deg` degrees about `axis`.
const quatAbout = (axis, deg) =>
  new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...axis).normalize(), (deg * Math.PI) / 180)

describe('quatToEulerDeg', () => {
  it('identity quaternion → zero Euler angles', () => {
    const [rx, ry, rz] = quatToEulerDeg([0, 0, 0, 1])
    expect(rx).toBeCloseTo(0)
    expect(ry).toBeCloseTo(0)
    expect(rz).toBeCloseTo(0)
  })

  it('90° about X → [90, 0, 0] degrees', () => {
    const q = quatAbout([1, 0, 0], 90)
    const [rx, ry, rz] = quatToEulerDeg([q.x, q.y, q.z, q.w])
    expect(rx).toBeCloseTo(90)
    expect(ry).toBeCloseTo(0)
    expect(rz).toBeCloseTo(0)
  })
})

describe('eulerDegToQuat', () => {
  it('zero Euler → identity quaternion', () => {
    const [x, y, z, w] = eulerDegToQuat(0, 0, 0)
    expect(x).toBeCloseTo(0)
    expect(y).toBeCloseTo(0)
    expect(z).toBeCloseTo(0)
    expect(w).toBeCloseTo(1)
  })

  it('matches THREE for 90° about X', () => {
    const expected = quatAbout([1, 0, 0], 90)
    const [x, y, z, w] = eulerDegToQuat(90, 0, 0)
    expect(x).toBeCloseTo(expected.x)
    expect(y).toBeCloseTo(expected.y)
    expect(z).toBeCloseTo(expected.z)
    expect(w).toBeCloseTo(expected.w)
  })

  it('round-trips euler → quat → euler', () => {
    const [x, y, z, w] = eulerDegToQuat(30, 45, -60)
    const [rx, ry, rz] = quatToEulerDeg([x, y, z, w])
    expect(rx).toBeCloseTo(30)
    expect(ry).toBeCloseTo(45)
    expect(rz).toBeCloseTo(-60)
  })
})

describe('extractJointAngleDeg', () => {
  const jointZ = { axis_direction: [0, 0, 1] }

  it('returns the signed angle about the joint axis', () => {
    const q90 = quatAbout([0, 0, 1], 90)
    expect(extractJointAngleDeg(q90, jointZ)).toBeCloseTo(90)
    const qNeg = quatAbout([0, 0, 1], -90)
    expect(extractJointAngleDeg(qNeg, jointZ)).toBeCloseTo(-90)
  })

  it('identity rotation → 0', () => {
    expect(extractJointAngleDeg(new THREE.Quaternion(0, 0, 0, 1), jointZ)).toBeCloseTo(0)
  })

  it('guards the degenerate len≈0 case (returns 0)', () => {
    // 180° about X, measured against the Z axis: dot=0 and w=0 → len=0.
    expect(extractJointAngleDeg({ x: 1, y: 0, z: 0, w: 0 }, jointZ)).toBe(0)
  })
})

describe('posEulerFromMatrix', () => {
  it('recovers translation and XYZ Euler degrees from a compose', () => {
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2)
    const m = new THREE.Matrix4().compose(new THREE.Vector3(5, 6, 7), q, new THREE.Vector3(1, 1, 1))
    const { pos, euler } = posEulerFromMatrix(m)
    expect(pos[0]).toBeCloseTo(5); expect(pos[1]).toBeCloseTo(6); expect(pos[2]).toBeCloseTo(7)
    expect(euler[0]).toBeCloseTo(90); expect(euler[1]).toBeCloseTo(0); expect(euler[2]).toBeCloseTo(0)
  })
  it('identity matrix → origin + zero Euler', () => {
    const { pos, euler } = posEulerFromMatrix(new THREE.Matrix4())
    expect(pos).toEqual([0, 0, 0])
    euler.forEach(e => expect(e).toBeCloseTo(0))
  })
})
