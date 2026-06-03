import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { beltLoopLength } from './belt_geometry.js'
import { beltRiderCtx, beltRiderFill } from './belt_rider.js'

describe('beltRiderCtx (guard paths)', () => {
  it('null when the rider is missing or has no local_transform', () => {
    expect(beltRiderCtx(null, 'r1')).toBeNull()
    expect(beltRiderCtx({ belt_riders: [] }, 'r1')).toBeNull()
    expect(beltRiderCtx({ belt_riders: [{ id: 'r1' }] }, 'r1')).toBeNull() // no local_transform
  })
  it('null when the belt path is missing', () => {
    const asm = { belt_riders: [{ id: 'r1', local_transform: {}, belt_path_id: 'bX' }], belt_paths: [] }
    expect(beltRiderCtx(asm, 'r1')).toBeNull()
  })
})

describe('beltRiderFill', () => {
  // Square loop in the XY plane → L=40; tangent at arc 0 is +x.
  const points = [
    new THREE.Vector3(0, 0, 0), new THREE.Vector3(10, 0, 0),
    new THREE.Vector3(10, 10, 0), new THREE.Vector3(0, 10, 0),
  ]
  const ctx = { points, planeNormal: [0, 0, 1], L: beltLoopLength(points), rider: { arc_param: 0 } }

  it('counts copies from the footprint along the tangent', () => {
    // footprint = |5*1| = 5 along +x → 40/5 = 8 copies.
    expect(beltRiderFill(ctx, { x: 5, y: 1, z: 1 })).toEqual({ count: 8, spacingNm: 5, footprintNm: 5 })
  })
  it('falls back to L/4 footprint when no instance size', () => {
    // footprint = 40/4 = 10 → 4 copies.
    expect(beltRiderFill(ctx, null)).toEqual({ count: 4, spacingNm: 10, footprintNm: 10 })
  })
  it('null for null ctx', () => {
    expect(beltRiderFill(null, { x: 5, y: 1, z: 1 })).toBeNull()
  })
})
