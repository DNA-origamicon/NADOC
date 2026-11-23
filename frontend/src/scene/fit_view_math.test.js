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

it.each([0.35, 1, 2.4])('fits all corners at aspect %s from an oblique view', aspect => {
  const box = new THREE.Box3(new THREE.Vector3(-80, -60, -40), new THREE.Vector3(80, 60, 40))
  const camera = new THREE.PerspectiveCamera(55, aspect, .1, 10000)
  camera.zoom = 1.5
  camera.updateProjectionMatrix()
  const pose = fitViewPose(box, new THREE.Vector3(1, 1, 1), new THREE.Vector3(), camera.getEffectiveFOV(), aspect)
  camera.position.copy(pose.position); camera.lookAt(pose.target); camera.updateMatrixWorld()
  for (const x of [-80, 80]) for (const y of [-60, 60]) for (const z of [-40, 40]) {
    const p = new THREE.Vector3(x, y, z).project(camera)
    expect(Math.abs(p.x)).toBeLessThan(1)
    expect(Math.abs(p.y)).toBeLessThan(1)
    expect(Math.abs(p.z)).toBeLessThan(1)
  }
})
