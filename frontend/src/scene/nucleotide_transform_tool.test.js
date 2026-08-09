import { describe, it, expect } from 'vitest'
import * as THREE from 'three'

import { transformBodyForTarget } from './nucleotide_transform_tool.js'

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
