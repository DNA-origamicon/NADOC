import { describe, it, expect } from 'vitest'
import * as THREE from 'three'

import { abstractPreviewUpdate, abstractResidueInfo, transformBodyForTarget } from './nucleotide_transform_tool.js'

describe('transformBodyForTarget', () => {
  const pivot = new THREE.Vector3(1, 2, 3)
  const translation = new THREE.Vector3(0.5, -1, 2)
  const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2)

  it('serializes an ordinary/loop nucleotide identity', () => {
    expect(transformBodyForTarget(
      { helix_id: 'h1', bp_index: 7, direction: 'FORWARD', copy: 2 },
      pivot, translation, q,
    )).toMatchObject({
      kind: 'base', helix_id: 'h1', bp_index: 7, direction: 'FORWARD', copy_k: 2,
      pivot: [1, 2, 3], translation: [0.5, -1, 2], compose: true,
    })
  })

  it('serializes a crossover-extra-base identity', () => {
    expect(transformBodyForTarget(
      { helix_id: '__xb__', crossover_id: 'xo:with:colons', k: 1 },
      pivot, translation, q,
    )).toMatchObject({
      kind: 'extra_base', crossover_id: 'xo:with:colons', extra_base_k: 1,
      pivot: [1, 2, 3], translation: [0.5, -1, 2], compose: true,
    })
  })
})

describe('abstract nucleotide projection', () => {
  const nuc = {
    helix_id: 'h1', bp_index: 7, direction: 'FORWARD', copy: 0,
    backbone_position: [1, 0, 0], base_position: [0, 1, 0],
    base_normal: [1, 0, 0], axis_tangent: [0, 0, 1],
  }

  it('finds the same selected residue in full geometry', () => {
    const info = abstractResidueInfo(
      { helix_id: 'h1', bp_index: 7, direction: 'FORWARD', copy: 0 }, [nuc])
    expect(info.nuc).toBe(nuc)
    expect(info.centroid.toArray()).toEqual([1, 0, 0])
  })

  it('previews the same rigid delta on the bead and nucleotide frame', () => {
    const info = { nuc, centroid: new THREE.Vector3(1, 0, 0) }
    const matrix = new THREE.Matrix4().makeRotationZ(Math.PI / 2)
    const update = abstractPreviewUpdate(info, matrix)
    expect(update.backbone_position[0]).toBeCloseTo(0)
    expect(update.backbone_position[1]).toBeCloseTo(1)
    const beforeOffset = new THREE.Vector3(...nuc.base_position)
      .sub(new THREE.Vector3(...nuc.backbone_position))
    const afterOffset = new THREE.Vector3(...update.base_position)
      .sub(new THREE.Vector3(...update.backbone_position))
    expect(afterOffset.length()).toBeCloseTo(beforeOffset.length())
    expect(update.nx).toBeCloseTo(0)
    expect(update.ny).toBeCloseTo(1)
    expect(update.tz).toBeCloseTo(1)
  })
})
