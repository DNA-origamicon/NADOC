import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import { screenPlaneCameraUp } from './camera_basis.js'

describe('screenPlaneCameraUp', () => {
  it('removes the forward/backward component from the reset-camera up vector', () => {
    const position = new THREE.Vector3(6, 3, 7)
    const target = new THREE.Vector3(0, 0, 7)
    const up = screenPlaneCameraUp(position, target, new THREE.Vector3(0, 1, 0))
    const eye = position.clone().sub(target).normalize()

    expect(up.length()).toBeCloseTo(1)
    expect(up.dot(eye)).toBeCloseTo(0)
    expect(up.toArray()).toEqual([
      expect.closeTo(-0.4472135955),
      expect.closeTo(0.894427191),
      expect.closeTo(0),
    ])
  })

  it('chooses a finite screen-up direction when preferred up is parallel to view', () => {
    const up = screenPlaneCameraUp(
      new THREE.Vector3(0, 4, 0),
      new THREE.Vector3(0, 0, 0),
      new THREE.Vector3(0, 1, 0),
    )
    expect(up.toArray().every(Number.isFinite)).toBe(true)
    expect(up.length()).toBeCloseTo(1)
    expect(up.y).toBeCloseTo(0)
  })
})
