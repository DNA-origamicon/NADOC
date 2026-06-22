import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { CYLINDER_GEO } from './atomistic_renderer/geometry_builder.js'

// Regression for the oxDNA-display atomistic overlay drawing long bonds across the
// model: when a position overlay (applyPositionLerp) leaves a nucleotide at its
// design position while its neighbour moved to the relaxed frame, the bond between
// them stretches over the whole structure. The renderer must HIDE such bonds.

function _bondMesh(scene) {
  return scene.children.find((o) => o.isInstancedMesh && o.geometry === CYLINDER_GEO)
}

function bondCylinderScaleY(scene, index = 0) {
  // The bond mesh is the InstancedMesh built on CYLINDER_GEO (element meshes use
  // the sphere geo). Decompose its instance matrix; cylinder length is scaleY.
  const bondMesh = _bondMesh(scene)
  if (!bondMesh) return null
  const m = new THREE.Matrix4()
  bondMesh.getMatrixAt(index, m)
  const pos = new THREE.Vector3(), quat = new THREE.Quaternion(), scl = new THREE.Vector3()
  m.decompose(pos, quat, scl)
  return scl.y
}

function makeTwoAtomBond() {
  const scene = new THREE.Scene()
  const ar = initAtomisticRenderer(scene)
  ar.setMode('ballstick')
  ar.update({
    atoms: [
      { serial: 0, element: 'P', helix_id: 'h0', x: 0, y: 0, z: 0 },
      { serial: 1, element: 'O', helix_id: 'h0', x: 0.15, y: 0, z: 0 },
    ],
    bonds: [[0, 1]],
  })
  return { scene, ar }
}

describe('atomistic_renderer applyPositionLerp bond cutoff', () => {
  it('draws a bond when the two atoms are a normal bond length apart', () => {
    const { scene, ar } = makeTwoAtomBond()
    // serial 0 at origin, serial 1 at 0.15 nm — a real backbone-ish bond.
    const flat = [0, 0, 0, 0.15, 0, 0]
    ar.applyPositionLerp(flat, flat, 0, null, [], null)
    expect(bondCylinderScaleY(scene)).toBeCloseTo(0.15, 5)
  })

  it('hides a bond stretched across the structure (un-overridden nucleotide)', () => {
    const { scene, ar } = makeTwoAtomBond()
    // serial 1 stranded 5 nm away (its design position) while serial 0 relaxed.
    const flat = [0, 0, 0, 5, 0, 0]
    ar.applyPositionLerp(flat, flat, 0, null, [], null)
    expect(bondCylinderScaleY(scene)).toBe(0)   // zero-scale → invisible, not a line across the model
  })

  it('re-shows the bond once the atoms come back within range', () => {
    const { scene, ar } = makeTwoAtomBond()
    ar.applyPositionLerp([0, 0, 0, 5, 0, 0], [0, 0, 0, 5, 0, 0], 0, null, [], null)
    expect(bondCylinderScaleY(scene)).toBe(0)              // hidden first…
    ar.applyPositionLerp([0, 0, 0, 0.16, 0, 0], [0, 0, 0, 0.16, 0, 0], 0, null, [], null)
    expect(bondCylinderScaleY(scene)).toBeCloseTo(0.16, 5) // …restored when back in range
  })
})

// AF-ATOM P2 — renderer↔audit parity: the renderer must DRAW exactly what the
// backend audit (atomistic_validation.audit_bonds) classifies as visible, and HIDE
// exactly what it lists in `hidden_by_renderer` (> _MAX_BOND_NM = 1.0 nm). This ties
// the on-screen sticks to the audited model bond-for-bond, so a stretched bond is
// always either drawn at its true length or provably hidden (never lost, never a
// phantom line). The backend RENDER_HIDE_NM and the renderer _MAX_BOND_NM are the
// same 1.0 nm cutoff, so the visible/hidden partition here == the audit's.
describe('atomistic_renderer ↔ audit parity (AF-ATOM P2)', () => {
  // Five bonds at known lengths; the >1.0 nm ones (indices 2 and 4) are exactly the
  // set the backend audit reports as hidden_by_renderer.
  const ATOMS = [
    { serial: 0, element: 'O', helix_id: 'h0', x: 0, y: 0, z: 0 },
    { serial: 1, element: 'P', helix_id: 'h0', x: 0.15, y: 0, z: 0 },     // 0.15 → drawn
    { serial: 2, element: 'O', helix_id: 'h0', x: 10, y: 0, z: 0 },
    { serial: 3, element: 'P', helix_id: 'h0', x: 10.5, y: 0, z: 0 },     // 0.50 → drawn
    { serial: 4, element: 'O', helix_id: 'h0', x: 20, y: 0, z: 0 },
    { serial: 5, element: 'P', helix_id: 'h0', x: 21.5, y: 0, z: 0 },     // 1.50 → HIDDEN
    { serial: 6, element: 'O', helix_id: 'h0', x: 30, y: 0, z: 0 },
    { serial: 7, element: 'P', helix_id: 'h0', x: 30.16, y: 0, z: 0 },    // 0.16 → drawn
    { serial: 8, element: 'O', helix_id: 'h0', x: 40, y: 0, z: 0 },
    { serial: 9, element: 'P', helix_id: 'h0', x: 42, y: 0, z: 0 },       // 2.00 → HIDDEN
  ]
  const BONDS = [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]
  const EXPECTED_LEN = [0.15, 0.5, 1.5, 0.16, 2.0]

  it('hides exactly the >1nm bonds and draws every other at its true atom distance', () => {
    const scene = new THREE.Scene()
    const ar = initAtomisticRenderer(scene)
    ar.setMode('ballstick')
    ar.update({ atoms: ATOMS, bonds: BONDS })
    const flat = ATOMS.flatMap((a) => [a.x, a.y, a.z])
    ar.applyPositionLerp(flat, flat, 0, null, [], null)

    const auditHidden = []   // what the renderer hid (scaleY 0)
    const auditDrawn = []    // what it drew, with its length
    for (let i = 0; i < BONDS.length; i++) {
      const sy = bondCylinderScaleY(scene, i)
      if (sy === 0) auditHidden.push(i)
      else auditDrawn.push([i, sy])
    }
    // Hidden set == bonds longer than the cutoff (the backend hidden_by_renderer set).
    expect(auditHidden).toEqual([2, 4])
    // Every drawn stick spans its two atoms at the true length (no phantom geometry).
    for (const [i, sy] of auditDrawn) expect(sy).toBeCloseTo(EXPECTED_LEN[i], 5)
  })
})
