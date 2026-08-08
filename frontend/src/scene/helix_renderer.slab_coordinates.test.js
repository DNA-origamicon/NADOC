import { describe, expect, it } from 'vitest'
import * as THREE from 'three'

import {
  SLAB_BEAD_CENTER_PENETRATION,
  pairedSlabCenter,
  slabConnectionCorner,
  slabQuaternion,
  translatedBasePosition,
} from './helix_renderer.js'

describe('base slab coordinate abstraction', () => {
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

  it('moves an overlay base site by exactly the live bead displacement', () => {
    const base = new THREE.Vector3(1, 2, 3)
    const equilibriumBead = new THREE.Vector3(2, 4, 6)
    const liveBead = new THREE.Vector3(7, 1, 8)

    expect(translatedBasePosition(base, equilibriumBead, liveBead).toArray())
      .toEqual([6, -1, 5])
  })

  it('does not invent an offset when bead and base positions coincide', () => {
    const basePosition = [1.25, -2.5, 3.75]

    const center = pairedSlabCenter(
      new THREE.Vector3(1.25, -2.5, 3.75),
      new THREE.Vector3(...basePosition),
      null,
      new THREE.Vector3(0, 0, 1),
      new THREE.Vector3(1, 0, 0),
    )

    expect(center.toArray()).toEqual(basePosition)
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

  it('makes paired slab faces coplanar while extending each slab to its bead', () => {
    const tangent = new THREE.Vector3(0, 0, 1)
    const fBase = new THREE.Vector3(-0.3, 0, -0.04)
    const rBase = new THREE.Vector3(0.3, 0, 0.08)

    const fBead = new THREE.Vector3(-0.8, 0, 0)
    const rBead = new THREE.Vector3(0.8, 0, 0)
    const fCenter = pairedSlabCenter(fBead, fBase, rBase, tangent, new THREE.Vector3(1, 0, 0))
    const rCenter = pairedSlabCenter(rBead, rBase, fBase, tangent, new THREE.Vector3(-1, 0, 0))

    expect(fCenter.dot(tangent)).toBeCloseTo(rCenter.dot(tangent), 12)
    expect(fCenter.z).toBeCloseTo(0.02, 12)
    expect(rCenter.z).toBeCloseTo(0.02, 12)
    expect(fCenter.x).toBeCloseTo(fBead.x + 0.35 - SLAB_BEAD_CENTER_PENETRATION, 12)
    expect(rCenter.x).toBeCloseTo(rBead.x - 0.35 + SLAB_BEAD_CENTER_PENETRATION, 12)
  })

  it('puts every largest-face corner of the real h_XY_0_1:0 pair on two shared planes', () => {
    // Exact measured-positioning payload from workspace/2hbx1.nadoc.
    const tangent = new THREE.Vector3(0, 0, 1)
    const f = {
      base: new THREE.Vector3(2.2440230786037487, 1.0199055183841632, 0.0326),
      normal: new THREE.Vector3(-0.8795879001177818, 0.4643044996934617, -0.10366512205556658),
    }
    const r = {
      base: new THREE.Vector3(1.6958987218200727, 1.3092417009443902, -0.032),
      normal: new THREE.Vector3(0.8795879001177818, -0.4643044996934617, 0.10366512205556658),
    }
    const fCenter = pairedSlabCenter(
      new THREE.Vector3(2.76, 1.0, -0.0152), f.base, r.base, tangent, f.normal,
    )
    const rCenter = pairedSlabCenter(
      new THREE.Vector3(1.2, 1.6, 0.0156), r.base, f.base, tangent, r.normal,
    )
    const fQuat = slabQuaternion(f.normal, tangent)
    const rQuat = slabQuaternion(r.normal, tangent)

    // GEO_UNIT_BOX dimensions after scaling: x=.30, y=.06, z=.70.  y=+/-0.03
    // are the two largest x*z faces.  Assert all four corners from BOTH slabs lie
    // on the same world plane for each sign, rather than checking centers only.
    for (const faceY of [-0.03, 0.03]) {
      const axialCoordinates = []
      for (const [center, quat] of [[fCenter, fQuat], [rCenter, rQuat]]) {
        for (const x of [-0.15, 0.15]) {
          for (const z of [-0.35, 0.35]) {
            const corner = new THREE.Vector3(x, faceY, z).applyQuaternion(quat).add(center)
            axialCoordinates.push(corner.dot(tangent))
          }
        }
      }
      expect(Math.max(...axialCoordinates) - Math.min(...axialCoordinates)).toBeLessThan(1e-12)
      expect(axialCoordinates[0]).toBeCloseTo(0.0003 + faceY, 12)
    }
  })
})
