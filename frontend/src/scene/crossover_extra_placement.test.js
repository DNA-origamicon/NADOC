import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import {
  buildCrossoverExtraPlacements,
  crossoverExtraBaseDefaultLocalPose,
} from './crossover_extra_placement.js'

describe('crossover extra-base placement abstraction', () => {
  it('assigns stable simulation identities when geometric order is reversed', () => {
    const p = buildCrossoverExtraPlacements({
      xoId: 'xo', count: 3, pointA: new THREE.Vector3(), control: new THREE.Vector3(1, 1, 0),
      pointB: new THREE.Vector3(2, 0, 0), helixAxis: new THREE.Vector3(0, 0, 1),
      simReversed: true,
    })
    expect(p.map(x => x.simK)).toEqual([2, 1, 0])
  })

  it('applies a saved pose exactly once to center and orientation', () => {
    const pose = new THREE.Matrix4().makeTranslation(4, 0, 0)
    const [p] = buildCrossoverExtraPlacements({
      xoId: 'xo', count: 1, pointA: new THREE.Vector3(), control: new THREE.Vector3(1, 1, 0),
      pointB: new THREE.Vector3(2, 0, 0), helixAxis: new THREE.Vector3(0, 0, 1),
      savedTransforms: new Map([[0, pose]]),
    })
    expect(p.center.x - p.sourceCenter.x).toBeCloseTo(4)
    expect(p.tangent.distanceTo(p.sourceTangent)).toBeLessThan(1e-14)
  })

  it.each([
    [false, [1.0350126516288711, -0.0677414490623244, -0.11119985396656734]],
    [true, [0.9294409122891801, -0.15898318445001028, 0.15187203661584792]],
  ])('uses the measured off-curve 1xT pose (reversed=%s)', (simReversed, expected) => {
    const [p] = buildCrossoverExtraPlacements({
      xoId: 'xo', count: 1, pointA: new THREE.Vector3(),
      control: new THREE.Vector3(1, -0.6, 0), pointB: new THREE.Vector3(2, 0, 0),
      helixAxis: new THREE.Vector3(0, 0, 1), simReversed,
    })
    expect(p.geometricCenter.toArray()).toEqual([1, -0.3, 0])
    expected.forEach((value, i) => expect(p.sourceCenter.getComponent(i)).toBeCloseTo(value, 12))
    expect(p.sourceCenter.distanceTo(p.geometricCenter)).toBeGreaterThan(0.2)
    expect(crossoverExtraBaseDefaultLocalPose(2, simReversed)).toBeNull()
  })
})
