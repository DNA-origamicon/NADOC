import { describe, expect, it } from 'vitest'
import * as THREE from 'three'

import {
  combinedGroupCentroid,
  composeGroupMemberTransform,
  computeClusterPivotFromEntries,
  computeClusterPivotFromGeometry,
  rebaseClusterTranslationForPivot,
  ssTetherViolated,
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

describe('combinedGroupCentroid', () => {
  it('averages each member\'s visual centroid (pivot + translation)', () => {
    const members = [
      { pivot: [0, 0, 0], translation: [2, 0, 0] },   // centroid (2,0,0)
      { pivot: [1, 1, 0], translation: [1, 3, 0] },   // centroid (2,4,0)
    ]
    expect(combinedGroupCentroid(members)).toEqual([2, 2, 0])
  })

  it('is rotation-invariant (a member spun about its own pivot keeps its centroid)', () => {
    const spun = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2)
    const members = [
      { pivot: [5, 0, 0], translation: [0, 0, 0], rotation: [spun.x, spun.y, spun.z, spun.w] },
      { pivot: [7, 0, 0], translation: [0, 0, 0] },
    ]
    expect(combinedGroupCentroid(members)).toEqual([6, 0, 0])
  })

  it('handles the empty group', () => {
    expect(combinedGroupCentroid([])).toEqual([0, 0, 0])
  })
})

describe('composeGroupMemberTransform (multi-cluster rigid move)', () => {
  // A member's original point p maps, under stored (pivot,translation,rotation), to the
  // rendered visual x. The composed transform must move every member's x by the SAME
  // rigid group delta (rotate about G by dummyQuat, translate so G→dummyPos) — that is
  // what "move both as though they were one cluster" means.
  function visualOf(p, m) {
    return applyClusterTransform(
      p, m.pivot, m.translation,
      new THREE.Quaternion(...m.rotation),
    )
  }
  function groupDelta(x, G, dummyQuat, dummyPos) {
    return new THREE.Vector3(...x)
      .sub(new THREE.Vector3(...G))
      .applyQuaternion(new THREE.Quaternion(...dummyQuat))
      .add(new THREE.Vector3(...dummyPos))
      .toArray()
  }

  it('composed transform reproduces the shared rigid delta for each member', () => {
    const q1 = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 4)
    const q2 = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 6)
    const members = [
      { pivot: [2, 0, 0], translation: [1, 1, 0], rotation: [q1.x, q1.y, q1.z, q1.w] },
      { pivot: [8, 2, 1], translation: [-2, 0, 3], rotation: [q2.x, q2.y, q2.z, q2.w] },
    ]
    const G = combinedGroupCentroid(members)

    // Arbitrary group drag: rotate 50° about a tilted axis, translate.
    const Rd = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 1, 0).normalize(), 0.87)
    const dummyQuat = [Rd.x, Rd.y, Rd.z, Rd.w]
    const dummyPos = [G[0] + 4, G[1] - 3, G[2] + 2]   // = G + Δ

    const probes = [[0, 0, 0], [3, -1, 2], [10, 5, -4]]
    for (const m of members) {
      const composed = composeGroupMemberTransform(m, G, dummyQuat, dummyPos)
      for (const p of probes) {
        const x = visualOf(p, m)                                   // where the bead is now
        const want = groupDelta(x, G, dummyQuat, dummyPos)         // where the group delta puts it
        const got = applyClusterTransform(                         // where the committed transform puts it
          p, composed.pivot, composed.translation,
          new THREE.Quaternion(...composed.rotation),
        )
        expect(got[0]).toBeCloseTo(want[0])
        expect(got[1]).toBeCloseTo(want[1])
        expect(got[2]).toBeCloseTo(want[2])
      }
    }
  })

  it('identity group delta (no drag) leaves each member\'s rendered geometry unchanged', () => {
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), 1.1)
    const m = { pivot: [3, 4, 5], translation: [1, -2, 6], rotation: [q.x, q.y, q.z, q.w] }
    const G = combinedGroupCentroid([m, { pivot: [0, 0, 0], translation: [0, 0, 0] }])
    const composed = composeGroupMemberTransform(m, G, [0, 0, 0, 1], G)   // Rd=I, dummyPos=G ⇒ Δ=0
    for (const p of [[1, 1, 1], [9, -3, 2]]) {
      const before = visualOf(p, m)
      const after = applyClusterTransform(
        p, composed.pivot, composed.translation, new THREE.Quaternion(...composed.rotation),
      )
      expect(after[0]).toBeCloseTo(before[0])
      expect(after[1]).toBeCloseTo(before[1])
      expect(after[2]).toBeCloseTo(before[2])
    }
  })
})

describe('ssTetherViolated (free-until-taut vs rigid strut)', () => {
  const C = 5.0
  it('free-until-taut: violated only when over-stretched', () => {
    expect(ssTetherViolated(false, 6.0, C)).toBe(true)   // over → taut
    expect(ssTetherViolated(false, 5.0, C)).toBe(false)  // exactly at contour
    expect(ssTetherViolated(false, 2.0, C)).toBe(false)  // slack (closer) → free
  })
  it('rigid strut: violated when over OR under length (resists compression)', () => {
    expect(ssTetherViolated(true, 6.0, C)).toBe(true)    // over → pull in
    expect(ssTetherViolated(true, 2.0, C)).toBe(true)    // under → push out
    expect(ssTetherViolated(true, 5.0, C)).toBe(false)   // exactly at rod length → satisfied
    expect(ssTetherViolated(true, 5.00005, C)).toBe(false) // within eps
  })
})
