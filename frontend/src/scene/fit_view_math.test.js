import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import { fitViewPose } from './fit_view_math.js'

describe('fitViewPose', () => {
  it('recovers a finite pose when camera and orbit target are NaN', () => {
    const box = new THREE.Box3(
      new THREE.Vector3(0, 0, 0), new THREE.Vector3(2, 4, 10),
    )
    const bad = new THREE.Vector3(NaN, NaN, NaN)
    const pose = fitViewPose(box, bad, bad, 55)
    expect(pose.target.toArray()).toEqual([1, 2, 5])
    expect(pose.position.toArray().every(Number.isFinite)).toBe(true)
    expect(pose.position.z).toBeGreaterThan(pose.target.z)
  })

  it('rejects a non-finite bounding box', () => {
    const box = new THREE.Box3(
      new THREE.Vector3(NaN, 0, 0), new THREE.Vector3(1, 1, 1),
    )
    expect(fitViewPose(box, new THREE.Vector3(), new THREE.Vector3(), 55)).toBeNull()
  })
})
