import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { buildCrossoverExtraPlacements } from './crossover_extra_placement.js'

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
    expect(p.tangent.toArray()).toEqual(p.sourceTangent.toArray())
  })
})
