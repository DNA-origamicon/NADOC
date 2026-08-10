import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { buildCrossoverConnections, updateExtraBaseInstances, partitionExtraBaseUpdates, setExtraBaseConnectors, setExtraBaseSlabConnectors, hideExtraBaseConnectors, extraBaseConnectorScalarColors, domainEndKeys, extraBaseOrderReversed, simBeadIndex, simSlabQuaternion, setExtraBaseInstanceFromSim, SLAB_OFFSET, SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK, CONN_RADIUS } from './crossover_connections.js'
import { SLAB_CONNECTOR_RADIUS } from './helix_renderer.js'

function mockMesh(n) {
  const mats = Array.from({ length: n }, () => new THREE.Matrix4())
  const cols = new Array(n).fill(null)
  return {
    setMatrixAt(i, m) { mats[i].copy(m) },
    getMatrixAt(i, m) { m.copy(mats[i]) },
    setColorAt(i, c) { cols[i] = c.getHex() },
    _mats: mats,
    _cols: cols,
  }
}

function decompose(mesh, i) {
  const pos = new THREE.Vector3(), quat = new THREE.Quaternion(), scl = new THREE.Vector3()
  mesh._mats[i].decompose(pos, quat, scl)
  return { pos, quat, scl }
}

describe('saved crossover-extra transforms', () => {
  it('applies translation once to both bead and slab', () => {
    const xo = {
      id: 'xo1', extra_bases: 'T',
      half_a: { helix_id: 'a', index: 0, strand: 'FORWARD' },
      half_b: { helix_id: 'b', index: 0, strand: 'REVERSE' },
    }
    const design = {
      lattice_type: 'HONEYCOMB', crossovers: [xo], forced_ligations: [],
      strands: [{ id: 's', strand_type: 'staple', domains: [
        { helix_id: 'a', start_bp: 0, end_bp: 0, direction: 'FORWARD' },
        { helix_id: 'b', start_bp: 0, end_bp: 0, direction: 'REVERSE' },
      ] }],
      nucleotide_transforms: [{ kind: 'extra_base', crossover_id: 'xo1', extra_base_k: 0,
        pivot: [0, 0, 0], translation: [4, 0, 0], rotation: [0, 0, 0, 1] }],
    }
    const geometry = [
      { helix_id: 'a', bp_index: 0, direction: 'FORWARD', strand_id: 's', strand_type: 'staple',
        backbone_position: [0, 0, 0], axis_tangent: [0, 0, 1], base_normal: [1, 0, 0] },
      { helix_id: 'b', bp_index: 0, direction: 'REVERSE', strand_id: 's', strand_type: 'staple',
        backbone_position: [2, 0, 0], axis_tangent: [0, 0, 1], base_normal: [-1, 0, 0] },
    ]
    const result = buildCrossoverConnections(design, geometry, new Map(), {})
    const native = buildCrossoverConnections(
      { ...design, nucleotide_transforms: [] }, geometry, new Map(), {},
    )
    const bm = new THREE.Matrix4(), sm = new THREE.Matrix4()
    const nbm = new THREE.Matrix4(), nsm = new THREE.Matrix4()
    result.beadsMesh.getMatrixAt(0, bm); result.slabsMesh.getMatrixAt(0, sm)
    native.beadsMesh.getMatrixAt(0, nbm); native.slabsMesh.getMatrixAt(0, nsm)
    const bead = new THREE.Vector3().setFromMatrixPosition(bm)
    const slab = new THREE.Vector3().setFromMatrixPosition(sm)
    const nativeBead = new THREE.Vector3().setFromMatrixPosition(nbm)
    const nativeSlab = new THREE.Vector3().setFromMatrixPosition(nsm)
    expect(bead.x - nativeBead.x).toBeCloseTo(4)
    expect(slab.x - nativeSlab.x).toBeCloseTo(4) // saved translation applied once
  })

  it('keeps the saved pose through a live arc refresh', () => {
    const beads = mockMesh(1), slabs = mockMesh(1)
    const nativeBeads = mockMesh(1), nativeSlabs = mockMesh(1)
    const pose = new THREE.Matrix4().makeTranslation(4, 0, 0)
    updateExtraBaseInstances(
      beads, slabs, 0, 1,
      new THREE.Vector3(0, 0, 0), new THREE.Vector3(1, 1, 0),
      new THREE.Vector3(2, 0, 0), new THREE.Vector3(0, 0, 1),
      false, new Map([[0, pose]]),
    )
    updateExtraBaseInstances(
      nativeBeads, nativeSlabs, 0, 1,
      new THREE.Vector3(0, 0, 0), new THREE.Vector3(1, 1, 0),
      new THREE.Vector3(2, 0, 0), new THREE.Vector3(0, 0, 1),
    )
    expect(decompose(beads, 0).pos.x - decompose(nativeBeads, 0).pos.x).toBeCloseTo(4)
    expect(decompose(slabs, 0).pos.x - decompose(nativeSlabs, 0).pos.x).toBeCloseTo(4)
  })
})

describe('setExtraBaseConnectors', () => {
  const V = (x, y, z) => new THREE.Vector3(x, y, z)

  it('places one cone per segment: midpoint position, full-length height, CONN_RADIUS girth', () => {
    const mesh = mockMesh(2)
    // path: posA(0,0,0) → bead(1,0,0) → posB(3,0,0): 2 segments of length 1 and 2.
    setExtraBaseConnectors(mesh, 0, [V(0, 0, 0), V(1, 0, 0), V(3, 0, 0)], 2, 0x00ff00)

    const s0 = decompose(mesh, 0)
    expect(s0.pos.x).toBeCloseTo(0.5)        // midpoint of [0,1]
    expect(s0.scl.y).toBeCloseTo(1)          // segment length
    expect(s0.scl.x).toBeCloseTo(CONN_RADIUS)
    expect(s0.scl.z).toBeCloseTo(CONN_RADIUS)

    const s1 = decompose(mesh, 1)
    expect(s1.pos.x).toBeCloseTo(2)          // midpoint of [1,3]
    expect(s1.scl.y).toBeCloseTo(2)          // segment length
    expect(mesh._cols[0]).toBe(0x00ff00)     // colored when colorHex given
  })

  it('writes into the arc-specific slot range (connStartIdx offset)', () => {
    const mesh = mockMesh(4)
    setExtraBaseConnectors(mesh, 2, [V(0, 0, 0), V(0, 4, 0)], 1, null)
    const s = decompose(mesh, 2)
    expect(s.pos.y).toBeCloseTo(2)
    expect(s.scl.y).toBeCloseTo(4)
    expect(mesh._cols[2]).toBeNull()         // null colorHex leaves color untouched
  })
})

describe('setExtraBaseSlabConnectors', () => {
  it('draws the standard Full-representation rod from bead to the slab N3 corner', () => {
    const beads = mockMesh(1), slabs = mockMesh(1), rods = mockMesh(1)
    beads.setMatrixAt(0, new THREE.Matrix4().compose(
      new THREE.Vector3(0, 0, 0), new THREE.Quaternion(), new THREE.Vector3(1, 1, 1),
    ))
    slabs.setMatrixAt(0, new THREE.Matrix4().compose(
      new THREE.Vector3(1, 0, 0), new THREE.Quaternion(),
      new THREE.Vector3(SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK),
    ))

    setExtraBaseSlabConnectors(beads, slabs, rods, 0, 1, 0xabcdef)

    // Identity slab: N3-side corner = center + (+length/2, 0, +thickness/2).
    const corner = new THREE.Vector3(1 + SLAB_LENGTH / 2, 0, SLAB_THICK / 2)
    const rod = decompose(rods, 0)
    expect(rod.pos.distanceTo(corner.clone().multiplyScalar(0.5))).toBeCloseTo(0, 8)
    expect(rod.scl.y).toBeCloseTo(corner.length(), 8)
    expect(rod.scl.x).toBeCloseTo(SLAB_CONNECTOR_RADIUS)
    expect(rod.scl.z).toBeCloseTo(SLAB_CONNECTOR_RADIUS)
    expect(rods._cols[0]).toBe(0xabcdef)
    const rodDirection = new THREE.Vector3(0, 1, 0).applyQuaternion(rod.quat)
    expect(rodDirection.distanceTo(corner.clone().normalize())).toBeCloseTo(0, 8)
  })

  it('zero-scales the rod whenever its residue bead/slab is hidden', () => {
    const beads = mockMesh(1), slabs = mockMesh(1), rods = mockMesh(1)
    beads.setMatrixAt(0, new THREE.Matrix4().makeScale(0, 0, 0))
    slabs.setMatrixAt(0, new THREE.Matrix4().compose(
      new THREE.Vector3(1, 0, 0), new THREE.Quaternion(),
      new THREE.Vector3(SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK),
    ))
    setExtraBaseSlabConnectors(beads, slabs, rods, 0, 1)
    expect(decompose(rods, 0).scl.length()).toBeCloseTo(0)
  })
})

describe('hideExtraBaseConnectors', () => {
  it('zeros the cone scale while keeping its position', () => {
    const mesh = mockMesh(1)
    setExtraBaseConnectors(mesh, 0, [new THREE.Vector3(0, 0, 0), new THREE.Vector3(2, 0, 0)], 1, null)
    const before = decompose(mesh, 0)
    hideExtraBaseConnectors(mesh, 0, 1)
    const after = decompose(mesh, 0)
    expect(after.scl.x).toBeCloseTo(0)
    expect(after.scl.y).toBeCloseTo(0)
    expect(after.scl.z).toBeCloseTo(0)
    expect(after.pos.x).toBeCloseTo(before.pos.x)   // position preserved
  })
})

describe('partitionExtraBaseUpdates', () => {
  it('passes real updates through untouched (no copy) when there are no inserts', () => {
    const ups = [{ helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [1, 2, 3] }]
    const { real, simXb } = partitionExtraBaseUpdates(ups)
    expect(real).toBe(ups)
    expect(simXb).toBeNull()
  })

  it('routes __xb__ updates into a per-crossover map keyed by k, keeping real ones', () => {
    const ups = [
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [0, 0, 0] },
      { helix_id: '__xb__', bp_index: 'xoA', direction: 0, backbone_position: [1, 1, 1], nx: 1, ny: 0, nz: 0 },
      { helix_id: '__xb__', bp_index: 'xoA', direction: 1, backbone_position: [2, 2, 2], nx: 0, ny: 1, nz: 0 },
      { helix_id: 'h1', bp_index: 5, direction: 'REVERSE', backbone_position: [9, 9, 9] },
    ]
    const { real, simXb } = partitionExtraBaseUpdates(ups)
    expect(real.map((u) => u.helix_id)).toEqual(['h0', 'h1'])
    expect(simXb.get('xoA').get(0).pos).toEqual([1, 1, 1])
    expect(simXb.get('xoA').get(0).normal).toEqual([1, 0, 0])
    expect(simXb.get('xoA').get(1).pos).toEqual([2, 2, 2])
    expect(simXb.get('xoA').get(1).normal).toEqual([0, 1, 0])
  })

  it('groups multiple crossovers independently', () => {
    const { simXb } = partitionExtraBaseUpdates([
      { helix_id: '__xb__', bp_index: 'xoA', direction: 0, backbone_position: [0, 0, 0] },
      { helix_id: '__xb__', bp_index: 'xoB', direction: 0, backbone_position: [1, 0, 0] },
    ])
    expect([...simXb.keys()].sort()).toEqual(['xoA', 'xoB'])
  })

  it('null updates (revert to geometry) → null map', () => {
    const { real, simXb } = partitionExtraBaseUpdates(null)
    expect(real).toBeNull()
    expect(simXb).toBeNull()
  })

  it('defaults a missing base normal to zero', () => {
    const { simXb } = partitionExtraBaseUpdates([
      { helix_id: '__xb__', bp_index: 'xoB', direction: 0, backbone_position: [0, 0, 0] },
    ])
    expect(simXb.get('xoB').get(0).normal).toEqual([0, 0, 0])
  })
})

describe('extraBaseConnectorScalarColors', () => {
  const arc = { xoId: 'xo7', beadCount: 3, nucA: { helix_id: 2, bp_index: 11, direction: 0 } }
  const lookupOf = (map) => (k) => map[k]

  it('colors each cone by the nucleotide it points AWAY from (helix_renderer fromNuc rule)', () => {
    const out = extraBaseConnectorScalarColors(arc, lookupOf({
      '2:11:0': 0x111111,
      '__xb__:xo7:0': 0x222222,
      '__xb__:xo7:1': 0x333333,
      '__xb__:xo7:2': 0x444444,
    }))
    // beadCount+1 segments: real nucA → eb0 → eb1 → eb2 → real nucB
    expect(out).toEqual([0x111111, 0x222222, 0x333333, 0x444444])
  })

  it('falls back to the 4-part copy-0 key for the real endpoint', () => {
    const out = extraBaseConnectorScalarColors(arc, lookupOf({ '2:11:0:0': 0xabcdef }))
    expect(out[0]).toBe(0xabcdef)
  })

  it('yields null for segments with no scalar datum (leave the cone as-is)', () => {
    const out = extraBaseConnectorScalarColors(arc, lookupOf({ '__xb__:xo7:1': 0x555555 }))
    expect(out).toEqual([null, null, 0x555555, null])
  })

  it('handles a missing endpoint nucleotide without throwing', () => {
    const out = extraBaseConnectorScalarColors({ xoId: 'xo9', beadCount: 1, nucA: null }, lookupOf({}))
    expect(out).toEqual([null, null])
  })

  it('maps the scalar key through the arc direction when the run is reversed', () => {
    // Bead s−1 holds insert simBeadIndex(s−1) — so on a reversed arc the cone leaving
    // bead 0 is coloured by insert n−1, not insert 0.
    const rev = { xoId: 'xo7', beadCount: 3, nucA: null, simReversed: true }
    const out = extraBaseConnectorScalarColors(rev, lookupOf({
      '__xb__:xo7:0': 0x222222,
      '__xb__:xo7:1': 0x333333,
      '__xb__:xo7:2': 0x444444,
    }))
    expect(out).toEqual([null, 0x444444, 0x333333, 0x222222])
  })
})

// ── Insert ordering (the 5′→3′ vs A→B mismatch) ──────────────────────────────

// Shape of workspace 2hb_2xT: two staples, each crossing between the same two helices
// but entering their junction from opposite sides.  Verified against that run's PSF
// covalent bonds — chain A runs half_a→k0→k1→half_b, chain B runs half_b→k0→k1→half_a.
const TWO_HB_DESIGN = {
  strands: [
    { id: 'stpl_XY_0_1', domains: [
      { helix_id: 'h_XY_0_1', start_bp: 7,  end_bp: 13, direction: 'FORWARD' },
      { helix_id: 'h_XY_1_1', start_bp: 13, end_bp: 7,  direction: 'REVERSE' },
    ] },
    { id: 'stpl_XY_1_1', domains: [
      { helix_id: 'h_XY_1_1', start_bp: 27, end_bp: 14, direction: 'REVERSE' },
      { helix_id: 'h_XY_0_1', start_bp: 14, end_bp: 27, direction: 'FORWARD' },
    ] },
  ],
}
const XO_A_TO_B = {   // 54c5689d — strand exits from half_a
  half_a: { helix_id: 'h_XY_0_1', index: 13, strand: 'FORWARD' },
  half_b: { helix_id: 'h_XY_1_1', index: 13, strand: 'REVERSE' },
}
const XO_B_TO_A = {   // 4a12dd44 — strand exits from half_b
  half_a: { helix_id: 'h_XY_0_1', index: 14, strand: 'FORWARD' },
  half_b: { helix_id: 'h_XY_1_1', index: 14, strand: 'REVERSE' },
}

describe('domainEndKeys', () => {
  it('collects helix:end_bp:direction for every domain of every strand', () => {
    const keys = domainEndKeys(TWO_HB_DESIGN)
    expect(keys.has('h_XY_0_1:13:FORWARD')).toBe(true)   // stpl_XY_0_1 exits here
    expect(keys.has('h_XY_1_1:14:REVERSE')).toBe(true)   // stpl_XY_1_1 exits here
    expect(keys.has('h_XY_0_1:14:FORWARD')).toBe(false)  // that is a domain START
    expect(keys.size).toBe(4)
  })

  it('tolerates a design with no strands', () => {
    expect(domainEndKeys(null).size).toBe(0)
    expect(domainEndKeys({}).size).toBe(0)
  })
})

describe('extraBaseOrderReversed', () => {
  const keys = domainEndKeys(TWO_HB_DESIGN)

  it('is false when the strand exits the junction from half_a (beads already run 5′→3′)', () => {
    expect(extraBaseOrderReversed(XO_A_TO_B, keys)).toBe(false)
  })

  it('is TRUE when the strand exits from half_b — the swapped-insert bug', () => {
    expect(extraBaseOrderReversed(XO_B_TO_A, keys)).toBe(true)
  })
})

describe('simBeadIndex', () => {
  it('is the identity on a forward arc', () => {
    expect([0, 1, 2].map(k => simBeadIndex(k, 3, false))).toEqual([0, 1, 2])
  })

  it('mirrors the run on a reversed arc', () => {
    expect([0, 1, 2].map(k => simBeadIndex(k, 3, true))).toEqual([2, 1, 0])
  })

  it('swaps the pair for the common TT insert', () => {
    expect([0, 1].map(k => simBeadIndex(k, 2, true))).toEqual([1, 0])
  })

  it('is its own inverse, so it maps bead→insert as well as insert→bead', () => {
    for (const n of [1, 2, 3, 5]) {
      for (let k = 0; k < n; k++) {
        expect(simBeadIndex(simBeadIndex(k, n, true), n, true)).toBe(k)
      }
    }
  })

  it('leaves a single insert alone in either direction', () => {
    expect(simBeadIndex(0, 1, true)).toBe(0)
    expect(simBeadIndex(0, 1, false)).toBe(0)
  })
})

// ── Simulated slab orientation ───────────────────────────────────────────────

describe('simSlabQuaternion', () => {
  const V = (x, y, z) => new THREE.Vector3(x, y, z)

  it('puts the long axis on the base normal and the thin axis on the helix axis', () => {
    // helix_renderer's convention: basis(tangential, axis, baseNormal), so local +Z
    // (the SLAB_THICK 0.70 axis) must land on the base normal and local +Y (the
    // SLAB_WIDTH 0.06 stacking axis) on the helix axis.
    const bn = V(1, 0, 0), axis = V(0, 0, 1)
    const q = simSlabQuaternion(bn, axis, new THREE.Quaternion())
    expect(V(0, 0, 1).applyQuaternion(q).distanceTo(bn)).toBeCloseTo(0, 6)
    expect(V(0, 1, 0).applyQuaternion(q).distanceTo(axis)).toBeCloseTo(0, 6)
    expect(V(1, 0, 0).applyQuaternion(q).distanceTo(V(0, 1, 0))).toBeCloseTo(0, 6)
  })

  it('is the identity when the base normal is +Z and the axis is +Y', () => {
    const q = simSlabQuaternion(V(0, 0, 1), V(0, 1, 0), new THREE.Quaternion())
    expect(q.angleTo(new THREE.Quaternion())).toBeCloseTo(0, 6)
  })

  it('stays finite when the base normal is parallel to the helix axis', () => {
    const q = simSlabQuaternion(V(0, 0, 1), V(0, 0, 1), new THREE.Quaternion())
    for (const c of [q.x, q.y, q.z, q.w]) expect(Number.isFinite(c)).toBe(true)
  })
})

describe('setExtraBaseInstanceFromSim', () => {
  it('puts the bead on the raw simulated position and the slab one SLAB_OFFSET along the base normal', () => {
    const beads = mockMesh(1), slabs = mockMesh(1)
    const axis = new THREE.Vector3(0, 0, 1)
    setExtraBaseInstanceFromSim(beads, slabs, 0, [2.044, 2.998, 4.365], [1, 0, 0], axis)

    const b = decompose(beads, 0)
    expect(b.pos.toArray()).toEqual([2.044, 2.998, 4.365])   // untouched MD coordinate
    expect(b.scl.x).toBeCloseTo(1)

    const s = decompose(slabs, 0)
    expect(s.pos.x).toBeCloseTo(2.044 + SLAB_OFFSET)         // shifted along the base normal
    expect(s.pos.y).toBeCloseTo(2.998)
    expect(s.scl.x).toBeCloseTo(SLAB_LENGTH)
    expect(s.scl.y).toBeCloseTo(SLAB_WIDTH)
    expect(s.scl.z).toBeCloseTo(SLAB_THICK)
    // Long axis follows the per-frame normal, not the design's static helix axis.
    const long = new THREE.Vector3(0, 0, 1).applyQuaternion(s.quat)
    expect(long.distanceTo(new THREE.Vector3(1, 0, 0))).toBeCloseTo(0, 6)
  })

  it('normalises a non-unit base normal instead of scaling the offset by it', () => {
    const beads = mockMesh(1), slabs = mockMesh(1)
    setExtraBaseInstanceFromSim(beads, slabs, 0, [0, 0, 0], [5, 0, 0], new THREE.Vector3(0, 0, 1))
    expect(decompose(slabs, 0).pos.x).toBeCloseTo(SLAB_OFFSET)
  })

  it('falls back to +Z for a zero-length base normal', () => {
    const beads = mockMesh(1), slabs = mockMesh(1)
    setExtraBaseInstanceFromSim(beads, slabs, 0, [0, 0, 0], [0, 0, 0], new THREE.Vector3(0, 1, 0))
    const s = decompose(slabs, 0)
    expect(s.pos.z).toBeCloseTo(SLAB_OFFSET)
    for (const c of s.pos.toArray()) expect(Number.isFinite(c)).toBe(true)
  })
})
