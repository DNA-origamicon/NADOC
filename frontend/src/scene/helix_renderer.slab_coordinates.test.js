import { describe, expect, it } from 'vitest'
import * as THREE from 'three'

import {
  slabConnectionCorner,
  slabCenterFromLocalOffset,
  slabQuaternion,
} from './helix_renderer.js'

describe('base slab coordinate abstraction', () => {
  it('makes native bead-to-slab registration independent of operation order', () => {
    const local = new THREE.Vector3(0.053484, 0.0155, 0.344735)
    const bead = new THREE.Vector3(4, -2, 7)
    const q1 = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), 0.7)
    const q2 = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -0.4)
    const translation = new THREE.Vector3(9, 3, -5)
    const combined = q2.clone().multiply(q1)

    const rotateThenTranslate = slabCenterFromLocalOffset(
      bead.clone().applyQuaternion(q1).applyQuaternion(q2).add(translation),
      local, combined,
    )
    const nativeCenter = slabCenterFromLocalOffset(bead, local, new THREE.Quaternion())
    const transformWholeResidue = nativeCenter.applyQuaternion(q1)
      .applyQuaternion(q2).add(translation)

    expect(rotateThenTranslate.distanceTo(transformWholeResidue)).toBeLessThan(1e-12)
  })
  it('anchors the bead connector on the N3-side slab corner, not an edge midpoint', () => {
    const center = new THREE.Vector3(2, 3, 4)
    const quat = new THREE.Quaternion()

    expect(slabConnectionCorner(center, quat, new THREE.Vector3(2, 3, 10)).toArray())
      .toEqual([2.15, 3, 4.35])
    expect(slabConnectionCorner(center, quat, new THREE.Vector3(2, 3, -10)).toArray())
      .toEqual([2.15, 3, 3.65])
  })

  it('keeps the N3 corner attached when the slab rotates', () => {
    const center = new THREE.Vector3(1, 0, 0)
    const quat = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 1, 0), Math.PI / 2,
    )
    const corner = slabConnectionCorner(center, quat, new THREE.Vector3(4, 0, 0))

    expect(corner.x).toBeCloseTo(1.35, 12)
    expect(corner.y).toBeCloseTo(0, 12)
    expect(corner.z).toBeCloseTo(-0.15, 12)
  })

  it('projects an axially staggered base_normal into the slab plane', () => {
    const baseNormal = new THREE.Vector3(-0.992072926104839, -0.0363646294956523, -0.12028683640127244)
    const axisTangent = new THREE.Vector3(0, 0, 1)
    const quaternion = slabQuaternion(baseNormal, axisTangent)
    const matrix = new THREE.Matrix4().makeRotationFromQuaternion(quaternion)

    const renderedNormal = new THREE.Vector3(0, 0, 1).applyMatrix4(matrix)
    const renderedTangent = new THREE.Vector3(0, 1, 0).applyMatrix4(matrix)

    expect(renderedNormal.dot(axisTangent)).toBeCloseTo(0, 12)
    expect(renderedTangent.distanceTo(axisTangent)).toBeLessThan(1e-12)
  })

})
