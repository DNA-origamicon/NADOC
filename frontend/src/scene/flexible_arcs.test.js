import { describe, it, expect, afterEach } from 'vitest'
import * as THREE from 'three'

import { initFlexibleArcs } from './flexible_arcs.js'
import { store } from '../state/store.js'

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

  it('only renders its bead/slab overlay for full and beads representations', () => {
    const scene = new THREE.Scene()
    const arcs = initFlexibleArcs(scene, makeRenderer(), () => ({}))
    arcs.rebuild(makeDesign())
    expect(beadMesh(arcs.group)).toBeTruthy()

    arcs.setRepresentation('cylinders')
    expect(arcs.group.visible).toBe(false)
    expect(arcs.group.children.length).toBe(0)

    arcs.setRepresentation('surface')
    expect(arcs.group.visible).toBe(false)
    expect(arcs.group.children.length).toBe(0)

    arcs.setRepresentation('beads')
    expect(arcs.group.visible).toBe(true)
    expect(beadMesh(arcs.group)).toBeTruthy()
  })
})

// ── Per-cluster colour + opacity ──────────────────────────────────────────────
// A flexible run bridges two cluster anchors, so it has to follow the cluster it
// belongs to. Before this, the three materials were module-level SINGLETONS shared
// by every connection's meshes — per-connection colour or fade was impossible,
// because one write hit every arc at once.

describe('flexible arcs — per-cluster display', () => {
  const clustered = (over = {}) => ({
    ...makeDesign(),
    // h_a and h_b each in their own cluster, so the two anchors differ.
    cluster_transforms: [
      { id: 'cA', helix_ids: ['h_a'], ...over.a },
      { id: 'cB', helix_ids: ['h_b'], ...over.b },
    ],
  })
  const mats = (group) => group.children.map(c => c.material).filter(Boolean)
  const build = (design) => {
    const scene = new THREE.Scene()
    const arcs = initFlexibleArcs(scene, makeRenderer(), () => ({}))
    arcs.rebuild(design)
    return arcs
  }

  afterEach(() => { store.setState({ coloringMode: 'strand' }) })

  it('gives every connection its OWN materials, not shared singletons', () => {
    // The pin for the actual defect: the three materials used to be created once
    // per FACTORY and handed to every connection's meshes, so no connection could
    // be coloured or faded independently — one write hit them all. Two connections
    // in ONE view is the case that exposes it.
    const two = clustered()
    two.flexible_connections = [
      two.flexible_connections[0],
      { ...two.flexible_connections[0], id: 'flx2' },
    ]
    const arcs = build(two)
    const all = mats(arcs.group)
    expect(all.length).toBeGreaterThanOrEqual(6)          // ≥3 meshes × 2 connections
    expect(new Set(all).size).toBe(all.length)            // every one distinct
  })

  it('fades ONE connection without touching its neighbour', () => {
    const two = clustered({ a: { opacity: 0.3 } })
    // flx2 anchors entirely within cluster B, so only flx1 straddles the faded one.
    two.flexible_connections = [
      two.flexible_connections[0],
      {
        ...two.flexible_connections[0], id: 'flx2',
        anchor_a: { strand_id: 'scaf', domain_index: 2, bp_index: 3, direction: 'FORWARD' },
      },
    ]
    const arcs = build(two)
    const opacities = mats(arcs.group).map(m => m.opacity)
    expect(opacities.some(o => Math.abs(o - 0.3) < 1e-6)).toBe(true)
    expect(opacities.some(o => o === 1)).toBe(true)
  })

  it('is opaque and magenta by default', () => {
    const arcs = build(makeDesign())
    for (const m of mats(arcs.group)) {
      expect(m.opacity).toBe(1)
      expect(m.transparent).toBe(false)
      expect(m.color.getHex()).toBe(0xff33cc)
    }
  })

  it('fades to its cluster opacity', () => {
    const arcs = build(clustered({ a: { opacity: 0.3 } }))
    for (const m of mats(arcs.group)) {
      expect(m.opacity).toBeCloseTo(0.3)
      expect(m.transparent).toBe(true)
    }
  })

  it('takes the LOWEST of the two anchors’ opacities', () => {
    const arcs = build(clustered({ a: { opacity: 0.8 }, b: { opacity: 0.35 } }))
    expect(mats(arcs.group)[0].opacity).toBeCloseTo(0.35)
  })

  it('keeps writing depth — a faded run must still cast the photo key shadow', () => {
    const arcs = build(clustered({ a: { opacity: 0.3 } }))
    for (const m of mats(arcs.group)) {
      expect(m.depthWrite).toBe(true)
      expect(m.userData.photoForceDepthWrite).toBe(true)
    }
  })

  it('takes the A-side cluster colour in cluster-coloring mode', () => {
    store.setState({ coloringMode: 'cluster' })
    const arcs = build(clustered({ a: { color: '#ff8800' }, b: { color: '#00ffcc' } }))
    for (const m of mats(arcs.group)) expect(m.color.getHex()).toBe(0xff8800)
  })

  it('ignores cluster colour in every OTHER coloring mode', () => {
    store.setState({ coloringMode: 'strand' })
    const arcs = build(clustered({ a: { color: '#ff8800' } }))
    expect(mats(arcs.group)[0].color.getHex()).toBe(0xff33cc)
  })

  it('…but still FADES in other coloring modes', () => {
    // Opacity is mode-independent by design; colour is cluster-mode only.
    store.setState({ coloringMode: 'strand' })
    const arcs = build(clustered({ a: { opacity: 0.3 } }))
    expect(mats(arcs.group)[0].opacity).toBeCloseTo(0.3)
  })

  it('refreshClusterDisplay repaints in place without rebuilding the geometry', () => {
    // It runs live while the swatch is dragged; rebuilding a TubeGeometry per
    // frame per connection would be the same lag the colour picker had.
    const arcs = build(clustered())
    const before = arcs.group.children.map(c => c.geometry)
    arcs.refreshClusterDisplay(clustered({ a: { opacity: 0.25 } }))
    expect(arcs.group.children.map(c => c.geometry)).toEqual(before)
    expect(mats(arcs.group)[0].opacity).toBeCloseTo(0.25)
  })

  it('refreshClusterDisplay does NOT latch the preview design', () => {
    // The preview design never reaches the store; a later render must use the
    // real one, not the transient patched copy.
    const arcs = build(clustered())
    arcs.refreshClusterDisplay(clustered({ a: { opacity: 0.25 } }))
    arcs.rebuild(clustered())               // the committed design, unstyled
    expect(mats(arcs.group)[0].opacity).toBe(1)
  })
})
