import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { clusterTransformAfterJointDelta } from './cluster_joint_math.js'

// Apply a cluster transform to a point: R*(p - pivot) + pivot + translation.
const xform = (p, c) => new THREE.Vector3(...p)
  .sub(new THREE.Vector3(...(c.pivot ?? [0, 0, 0])))
  .applyQuaternion(new THREE.Quaternion(...(c.rotation ?? [0, 0, 0, 1])))
  .add(new THREE.Vector3(...(c.pivot ?? [0, 0, 0])))
  .add(new THREE.Vector3(...(c.translation ?? [0, 0, 0])))

// Rotate a world point about the joint axis by delta.
const rotateAboutJoint = (x, J, axisDir, delta) => {
  const Jv = new THREE.Vector3(...J)
  const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...axisDir).normalize(), delta)
  return x.clone().sub(Jv).applyQuaternion(q).add(Jv)
}

const expectVecClose = (got, exp) => {
  expect(got.x).toBeCloseTo(exp.x, 5)
  expect(got.y).toBeCloseTo(exp.y, 5)
  expect(got.z).toBeCloseTo(exp.z, 5)
}

describe('clusterTransformAfterJointDelta', () => {
  const joint = { axis_origin: [5, 1, 0], axis_direction: [0, 0, 1] }
  const cluster = {
    pivot: [2, 0, 0],
    rotation: new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), 0.3).toArray(),
    translation: [1, 2, 3],
  }
  const pts = [[0, 0, 0], [3, 4, 5], [5, 1, 0], [-2, 7, 1]]

  it('composes a world rotation about the joint axis onto the existing transform', () => {
    const delta = 0.6
    const next = clusterTransformAfterJointDelta(cluster, joint, delta)
    for (const p of pts) {
      const expected = rotateAboutJoint(xform(p, cluster), joint.axis_origin, joint.axis_direction, delta)
      expectVecClose(xform(p, next), expected)
    }
  })

  it('zero delta leaves transformed positions unchanged', () => {
    const next = clusterTransformAfterJointDelta(cluster, joint, 0)
    for (const p of pts) expectVecClose(xform(p, next), xform(p, cluster))
  })

  it('preserves the pivot and other cluster fields (spread)', () => {
    const next = clusterTransformAfterJointDelta({ ...cluster, id: 'c1' }, joint, 0.2)
    expect(next.id).toBe('c1')
    expect(next.pivot).toEqual([2, 0, 0])
  })
})
