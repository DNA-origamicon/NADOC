import { describe, expect, it } from 'vitest'
import * as THREE from 'three'

import {
  computeClusterPivotFromEntries,
  computeClusterPivotFromGeometry,
  rebaseClusterTranslationForPivot,
} from './cluster_gizmo.js'

function nuc(helixId, position, extra = {}) {
  return {
    helix_id: helixId,
    backbone_position: position,
    ...extra,
  }
}

function applyClusterTransform(point, pivot, translation, rotation) {
  return new THREE.Vector3(...point)
    .sub(new THREE.Vector3(...pivot))
    .applyQuaternion(rotation)
    .add(new THREE.Vector3(...pivot))
    .add(new THREE.Vector3(...translation))
    .toArray()
}

describe('computeClusterPivotFromGeometry', () => {
  it('recovers the original centroid from translated and rotated cluster geometry', () => {
    const originalPoints = [
      [4, 0, 0],
      [6, 0, 0],
      [5, 2, 0],
    ]
    const oldPivot = [1, -2, 0]
    const translation = [3, 4, 1]
    const rotation = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 0, 1),
      Math.PI / 2,
    )

    const cluster = {
      helix_ids: ['h1'],
      domain_ids: [],
      pivot: oldPivot,
      translation,
      rotation: [rotation.x, rotation.y, rotation.z, rotation.w],
    }
    const geometry = originalPoints.map(p =>
      nuc('h1', applyClusterTransform(p, oldPivot, translation, rotation)),
    )

    const pivot = computeClusterPivotFromGeometry(cluster, { strands: [] }, geometry)

    expect(pivot[0]).toBeCloseTo(5)
    expect(pivot[1]).toBeCloseTo(2 / 3)
    expect(pivot[2]).toBeCloseTo(0)
  })

  it('uses only declared domain beads plus exclusive helices for mixed clusters', () => {
    const design = {
      strands: [
        { id: 's1', domains: [{ helix_id: 'bridge' }] },
      ],
    }
    const cluster = {
      helix_ids: ['exclusive', 'bridge'],
      domain_ids: [{ strand_id: 's1', domain_index: 0 }],
      pivot: [0, 0, 0],
      translation: [0, 0, 0],
      rotation: [0, 0, 0, 1],
    }
    const geometry = [
      nuc('exclusive', [0, 0, 0]),
      nuc('bridge', [10, 0, 0], { strand_id: 's1', domain_index: 0 }),
      nuc('bridge', [100, 0, 0], { strand_id: 'other', domain_index: 0 }),
    ]

    const pivot = computeClusterPivotFromGeometry(cluster, design, geometry)

    expect(pivot[0]).toBeCloseTo(5)
    expect(pivot[1]).toBeCloseTo(0)
    expect(pivot[2]).toBeCloseTo(0)
  })
})

describe('computeClusterPivotFromEntries', () => {
  it('uses rendered entry positions instead of stale nucleotide geometry', () => {
    const cluster = {
      helix_ids: ['h1'],
      domain_ids: [],
      pivot: [0, 0, 0],
      translation: [0, 0, 0],
      rotation: [0, 0, 0, 1],
    }
    const entries = [
      { nuc: nuc('h1', [100, 0, 0]), pos: new THREE.Vector3(1, 0, 0) },
      { nuc: nuc('h1', [100, 0, 0]), pos: new THREE.Vector3(3, 0, 0) },
      { nuc: nuc('other', [2, 0, 0]), pos: new THREE.Vector3(200, 0, 0) },
    ]

    const pivot = computeClusterPivotFromEntries(cluster, { strands: [] }, entries)

    expect(pivot[0]).toBeCloseTo(2)
    expect(pivot[1]).toBeCloseTo(0)
    expect(pivot[2]).toBeCloseTo(0)
  })
})

describe('rebaseClusterTranslationForPivot', () => {
  it('preserves the represented rigid transform when changing pivot', () => {
    const rotation = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 0, 1),
      Math.PI / 3,
    )
    const cluster = {
      pivot: [1, 2, 3],
      translation: [4, -2, 1],
      rotation: [rotation.x, rotation.y, rotation.z, rotation.w],
    }
    const nextPivot = [5, -1, 2]
    const point = new THREE.Vector3(7, 8, 9)

    const before = point.clone()
      .sub(new THREE.Vector3(...cluster.pivot))
      .applyQuaternion(rotation)
      .add(new THREE.Vector3(...cluster.pivot))
      .add(new THREE.Vector3(...cluster.translation))

    const nextTranslation = rebaseClusterTranslationForPivot(cluster, nextPivot)
    const after = point.clone()
      .sub(new THREE.Vector3(...nextPivot))
      .applyQuaternion(rotation)
      .add(new THREE.Vector3(...nextPivot))
      .add(new THREE.Vector3(...nextTranslation))

    expect(after.x).toBeCloseTo(before.x)
    expect(after.y).toBeCloseTo(before.y)
    expect(after.z).toBeCloseTo(before.z)
  })
})
