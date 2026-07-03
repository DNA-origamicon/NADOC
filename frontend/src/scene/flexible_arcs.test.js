import { describe, it, expect } from 'vitest'
import * as THREE from 'three'

import { initFlexibleArcs } from './flexible_arcs.js'

// One flexible connection: anchors on h_a (bp8) and h_b (bp3), two ssDNA run beads
// (h_a:0, h_b:0). helixOf resolves anc → `${domains[domain_index].helix_id}:bp:dir`.
function makeDesign() {
  return {
    strands: [{ id: 'scaf', domains: [
      { helix_id: 'h_a' }, { helix_id: 'h_a' }, { helix_id: 'h_b' }, { helix_id: 'h_b' },
    ] }],
    flexible_connections: [{
      id: 'flx1', cluster_a_id: 'a', cluster_b_id: 'b',
      anchor_a: { strand_id: 'scaf', domain_index: 0, bp_index: 8, direction: 'FORWARD' },
      anchor_b: { strand_id: 'scaf', domain_index: 3, bp_index: 3, direction: 'FORWARD' },
      n_ss_bases: 2, contour_length_nm: 4.0,
      segment_bead_keys: [
        { strand_id: 'scaf', domain_index: 1, bp_index: 0, direction: 'FORWARD' },
        { strand_id: 'scaf', domain_index: 2, bp_index: 0, direction: 'FORWARD' },
      ],
    }],
  }
}

function makeRenderer() {
  const entries = [
    { nuc: { helix_id: 'h_a', bp_index: 8, direction: 'FORWARD' }, pos: new THREE.Vector3(0, 0, 0) },
    { nuc: { helix_id: 'h_b', bp_index: 3, direction: 'FORWARD' }, pos: new THREE.Vector3(4, 0, 0) },
  ]
  return { getBackboneEntries: () => entries }
}

// The bead InstancedMesh is the one built on a SphereGeometry (slabs use a Box).
function beadMesh(group) {
  return group.children.find(
    (c) => c.isInstancedMesh && c.geometry?.type === 'SphereGeometry')
}
function beadTranslations(group) {
  const inst = beadMesh(group)
  const m = new THREE.Matrix4(), out = []
  for (let i = 0; i < inst.count; i++) {
    inst.getMatrixAt(i, m)
    out.push(new THREE.Vector3().setFromMatrixPosition(m))
  }
  return out
}

describe('flexible arcs — sim-position mode', () => {
  it('geometric-arc mode draws a tube + 2 run beads between the anchors', () => {
    const scene = new THREE.Scene()
    const arcs = initFlexibleArcs(scene, makeRenderer(), () => ({}))
    arcs.rebuild(makeDesign())
    const inst = beadMesh(arcs.group)
    expect(inst).toBeTruthy()
    expect(inst.count).toBe(2)
    // beads sit strictly between the anchors (x in (0,4)), not at a sim point.
    for (const p of beadTranslations(arcs.group)) {
      expect(p.x).toBeGreaterThan(0)
      expect(p.x).toBeLessThan(4)
    }
  })

  it('applySimPositions places the run beads at the frame positions', () => {
    const scene = new THREE.Scene()
    const arcs = initFlexibleArcs(scene, makeRenderer(), () => ({}))
    arcs.rebuild(makeDesign())
    arcs.applySimPositions([
      { helix_id: 'h_a', bp_index: 0, direction: 'FORWARD', backbone_position: [1, 2, 0], nx: 0, ny: 1, nz: 0 },
      { helix_id: 'h_b', bp_index: 0, direction: 'FORWARD', backbone_position: [3, 2, 0], nx: 0, ny: 1, nz: 0 },
    ])
    const pos = beadTranslations(arcs.group)
    expect(pos[0].toArray()).toEqual([1, 2, 0])
    expect(pos[1].toArray()).toEqual([3, 2, 0])
  })

  it('applySimPositions(null) reverts to the geometric arc', () => {
    const scene = new THREE.Scene()
    const arcs = initFlexibleArcs(scene, makeRenderer(), () => ({}))
    arcs.rebuild(makeDesign())
    arcs.applySimPositions([
      { helix_id: 'h_a', bp_index: 0, direction: 'FORWARD', backbone_position: [1, 2, 0] },
      { helix_id: 'h_b', bp_index: 0, direction: 'FORWARD', backbone_position: [3, 2, 0] },
    ])
    arcs.applySimPositions(null)
    // back on the arc between the anchors — no longer at the sim y=2.
    for (const p of beadTranslations(arcs.group)) {
      expect(Math.abs(p.y - 2)).toBeGreaterThan(0.01)
    }
  })

  it('falls back to the geometric arc when a run bead is absent from the frame', () => {
    const scene = new THREE.Scene()
    const arcs = initFlexibleArcs(scene, makeRenderer(), () => ({}))
    arcs.rebuild(makeDesign())
    arcs.applySimPositions([   // only ONE of the two run beads present
      { helix_id: 'h_a', bp_index: 0, direction: 'FORWARD', backbone_position: [1, 2, 0] },
    ])
    // no bead lands exactly on the lone sim point → geometric arc was used.
    const onSim = beadTranslations(arcs.group).some((p) => p.x === 1 && p.y === 2)
    expect(onSim).toBe(false)
  })
})
