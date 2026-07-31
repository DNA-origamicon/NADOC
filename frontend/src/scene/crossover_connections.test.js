import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { partitionExtraBaseUpdates, setExtraBaseConnectors, hideExtraBaseConnectors, extraBaseConnectorScalarColors, CONN_RADIUS } from './crossover_connections.js'

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
})
