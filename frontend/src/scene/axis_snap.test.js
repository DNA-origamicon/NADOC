import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { nearestWorkspaceAxis, signedAlong } from './axis_snap.js'

describe('nearestWorkspaceAxis', () => {
  it('snaps to the exact axis when looking straight down it', () => {
    const { normal, up } = nearestWorkspaceAxis(new THREE.Vector3(0, 0, 5))
    expect(normal.toArray()).toEqual([0, 0, 1])
    expect(up.toArray()).toEqual([0, 1, 0])
  })

  it('picks the closest axis for an off-axis direction', () => {
    // Mostly +X, a little +Y → nearest is +X.
    const { normal } = nearestWorkspaceAxis(new THREE.Vector3(0.9, 0.3, 0.1))
    expect(normal.toArray()).toEqual([1, 0, 0])
  })

  it('distinguishes the negative hemisphere', () => {
    const { normal } = nearestWorkspaceAxis(new THREE.Vector3(0, -3, 0.2))
    expect(normal.toArray()).toEqual([0, -1, 0])
  })

  it('uses +Z up for Y-axis views (view-cube convention)', () => {
    const { up } = nearestWorkspaceAxis(new THREE.Vector3(0, 1, 0))
    expect(up.toArray()).toEqual([0, 0, 1])
  })

  it('returns fresh clones (callers can mutate safely)', () => {
    const a = nearestWorkspaceAxis(new THREE.Vector3(1, 0, 0)).normal
    const b = nearestWorkspaceAxis(new THREE.Vector3(1, 0, 0)).normal
    a.multiplyScalar(2)
    expect(b.toArray()).toEqual([1, 0, 0])
  })
})

describe('signedAlong', () => {
  it('keeps the normal when the camera is already on its side', () => {
    const n = signedAlong(new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 0, 10))
    expect(n.toArray()).toEqual([0, 0, 1])
  })

  it('flips the normal to the camera hemisphere', () => {
    const n = signedAlong(new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 0, -10))
    expect(n.x).toBeCloseTo(0)
    expect(n.y).toBeCloseTo(0)
    expect(n.z).toBeCloseTo(-1)
  })

  it('normalizes the returned vector', () => {
    const n = signedAlong(new THREE.Vector3(0, 5, 0), new THREE.Vector3(0, 2, 0))
    expect(n.length()).toBeCloseTo(1)
    expect(n.toArray()).toEqual([0, 1, 0])
  })
})
