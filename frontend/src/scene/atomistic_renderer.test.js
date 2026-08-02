import { describe, it, expect, afterEach } from 'vitest'
import * as THREE from 'three'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { CYLINDER_GEO, SPHERE_GEO } from './atomistic_renderer/geometry_builder.js'
import { IMPOSTOR_QUAD } from './impostor_material.js'
import { BALL_RADIUS, ELEMENTS } from './atomistic_renderer/atom_palette.js'

// Regression for the oxDNA-display atomistic overlay drawing long bonds across the
// model: when a position overlay (applyPositionLerp) leaves a nucleotide at its
// design position while its neighbour moved to the relaxed frame, the bond between
// them stretches over the whole structure. The renderer must HIDE such bonds.

function _bondMesh(scene) {
  // By NAME, not by geometry identity: installing the per-instance alpha channel
  // clones the geometry off the shared CYLINDER_GEO template, so an identity test
  // silently stops finding the mesh once a cluster is faded.
  return scene.children.find((o) => o.isInstancedMesh && o.name === 'atomBonds')
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

// ── Sphere impostors, Phase C ────────────────────────────────────────────────
//
// These pin the two failure modes that are silent on screen rather than throwing:
// an instance matrix that double-applies the radius, and a fresh material (hence a
// fresh shader program) on every rebuild.

function _atomMeshes(scene) {
  return scene.children.filter((o) => o.isInstancedMesh && o.name === 'atomSpheres')
}

/** Uniform scale baked into instance `i`'s matrix. */
function instanceScale(mesh, i = 0) {
  const m = new THREE.Matrix4()
  mesh.getMatrixAt(i, m)
  const pos = new THREE.Vector3(), quat = new THREE.Quaternion(), scl = new THREE.Vector3()
  m.decompose(pos, quat, scl)
  return scl.x
}

function buildOneAtom(mode = 'ballstick') {
  const scene = new THREE.Scene()
  const ar = initAtomisticRenderer(scene)
  ar.setMode(mode)
  ar.update({ atoms: [{ serial: 0, element: 'P', helix_id: 'h0', x: 1, y: 2, z: 3 }], bonds: [] })
  return { scene, ar }
}

describe('atomistic_renderer sphere impostors (Phase C)', () => {
  afterEach(() => { delete window.NADOC_IMPOSTORS })

  describe('flag OFF (default) — unchanged real-sphere behaviour', () => {
    it('builds real SphereGeometry meshes', () => {
      const { scene } = buildOneAtom()
      const meshes = _atomMeshes(scene)
      expect(meshes).toHaveLength(1)
      expect(meshes[0].geometry).toBe(SPHERE_GEO)
      expect(meshes[0].material.userData.isImpostor).toBeUndefined()
    })

    // SPHERE_GEO is a UNIT sphere, so the instance matrix must carry the radius.
    // This is the pre-impostor behaviour, pinned so the elementScale refactor is
    // provably behaviour-preserving on the default path.
    it('bakes the radius into the instance matrix', () => {
      const { scene } = buildOneAtom('ballstick')
      expect(instanceScale(_atomMeshes(scene)[0])).toBeCloseTo(BALL_RADIUS, 6)
    })

    it('uses the per-element VdW radius in vdw mode', () => {
      const { scene } = buildOneAtom('vdw')
      expect(instanceScale(_atomMeshes(scene)[0])).toBeCloseTo(ELEMENTS.P.vdw, 6)
    })
  })

  describe('flag ON', () => {
    it('swaps in the 2-triangle quad and the impostor material', () => {
      window.NADOC_IMPOSTORS = true
      const { scene } = buildOneAtom()
      const mesh = _atomMeshes(scene)[0]
      expect(mesh.geometry).toBe(IMPOSTOR_QUAD)
      expect(mesh.geometry.attributes.position.count).toBe(4)   // quad, not a sphere
      expect(mesh.material.userData.isImpostor).toBe(true)
      expect(mesh.material.userData.impostorRadius).toBeCloseTo(BALL_RADIUS, 6)
    })

    // THE Phase-C regression. The shader computes
    //   v_impR = u_impostorRadius * length(instanceMatrix[0].xyz)
    // so a matrix that also carries the radius paints every atom at radius²
    // (0.07 nm → 0.005 nm). The matrix must be scale-free.
    it('leaves the instance matrix at scale 1 — the uniform owns the radius', () => {
      window.NADOC_IMPOSTORS = true
      const { scene } = buildOneAtom()
      expect(instanceScale(_atomMeshes(scene)[0])).toBeCloseTo(1, 6)
    })

    it('keeps the atom position in the instance matrix translation', () => {
      window.NADOC_IMPOSTORS = true
      const { scene } = buildOneAtom()
      const m = new THREE.Matrix4()
      _atomMeshes(scene)[0].getMatrixAt(0, m)
      const p = new THREE.Vector3().setFromMatrixPosition(m)
      expect([p.x, p.y, p.z]).toEqual([1, 2, 3])
    })

    it('installs the ray-vs-sphere raycast override', () => {
      window.NADOC_IMPOSTORS = true
      const { scene } = buildOneAtom()
      const mesh = _atomMeshes(scene)[0]
      // Own property → the instance-level override, not THREE's prototype method.
      expect(Object.prototype.hasOwnProperty.call(mesh, 'raycast')).toBe(true)
    })

    it('still applies position overlays at scale 1', () => {
      window.NADOC_IMPOSTORS = true
      const { scene, ar } = buildOneAtom()
      ar.applyPositionLerp([5, 6, 7], [5, 6, 7], 0, null, [], null)
      const mesh = _atomMeshes(scene)[0]
      const m = new THREE.Matrix4()
      mesh.getMatrixAt(0, m)
      expect(new THREE.Vector3().setFromMatrixPosition(m).toArray()).toEqual([5, 6, 7])
      expect(instanceScale(mesh)).toBeCloseTo(1, 6)
    })
  })

  // An impostor material declares a UNIQUE customProgramCacheKey (so its
  // u_impostorRadius gets bound), which means one material == one shader program.
  // The live MD display rebuilds every frame, so a fresh material per rebuild
  // would be a shader compile per frame plus an unbounded program-cache leak.
  it('reuses one material across rebuilds instead of recompiling per frame', () => {
    window.NADOC_IMPOSTORS = true
    const scene = new THREE.Scene()
    const ar = initAtomisticRenderer(scene)
    ar.setMode('ballstick')
    const atoms = [{ serial: 0, element: 'P', helix_id: 'h0', x: 0, y: 0, z: 0 }]
    ar.update({ atoms, bonds: [] })
    const first = _atomMeshes(scene)[0].material
    ar.update({ atoms, bonds: [] })
    const second = _atomMeshes(scene)[0].material
    expect(second).toBe(first)
  })

  it('gives each element its own material but keeps them stable across rebuilds', () => {
    const scene = new THREE.Scene()
    const ar = initAtomisticRenderer(scene)
    ar.setMode('vdw')   // per-element radii differ → distinct materials
    const atoms = [
      { serial: 0, element: 'P', helix_id: 'h0', x: 0, y: 0, z: 0 },
      { serial: 1, element: 'O', helix_id: 'h0', x: 1, y: 0, z: 0 },
    ]
    ar.update({ atoms, bonds: [] })
    const before = _atomMeshes(scene).map((m) => m.material)
    expect(new Set(before).size).toBe(2)
    ar.update({ atoms, bonds: [] })
    expect(_atomMeshes(scene).map((m) => m.material)).toEqual(before)
  })

  it('names its meshes so photo-mode resolves them by name, not material class', () => {
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
    expect(_atomMeshes(scene).length).toBeGreaterThan(0)
    expect(_bondMesh(scene).name).toBe('atomBonds')
  })
})

// The live NAMD MD-Display payload, end to end. `ws.py` sends heavy-atom bond
// topology once in 'ready' as FLAT universe-global serial pairs; md_panel caches it
// as an Int32Array and re-hands it to every frame's plain-object atom list. Two
// things must line up for sticks to appear at all, and both are easy to break:
// the flat typed array must take `_bondEnds`' ArrayBuffer.isView branch, and the
// object atom table (columnar === false) must resolve those serials via rowOfSerial.
describe('live MD ball-and-stick payload (flat Int32 serials + sparse object atoms)', () => {
  // Serials as MDAnalysis hands them out: universe-global, so the DNA heavy atoms of
  // a solvated box are sparse and never start at 0.
  const atoms = [
    { serial: 4021, element: 'P', helix_id: 'h0', x: 0,    y: 0, z: 0 },
    { serial: 4022, element: 'O', helix_id: 'h0', x: 0.15, y: 0, z: 0 },
    { serial: 9107, element: 'C', helix_id: 'h0', x: 0.30, y: 0, z: 0 },
  ]

  function render(bonds) {
    const scene = new THREE.Scene()
    const ar = initAtomisticRenderer(scene)
    ar.setMode('ballstick')
    ar.update({ atoms, bonds })
    return { scene, ar }
  }

  it('draws a cylinder per bond from a flat Int32Array of universe serials', () => {
    const { scene, ar } = render(Int32Array.from([4021, 4022, 4022, 9107]))
    const mesh = _bondMesh(scene)
    expect(mesh).toBeTruthy()
    expect(mesh.count).toBe(2)
    // 0.15 nm apart → a real covalent stick, not a zero-length or model-spanning one.
    expect(bondCylinderScaleY(scene, 0)).toBeCloseTo(0.15, 5)
    ar.dispose?.()
  })

  it('drops a bond reaching an atom absent from the frame, keeping the rest', () => {
    // 55555 is not in the atom table; rowOfSerial.get returns undefined. Before the
    // serial→row map that index would have been used as a ROW and drawn garbage.
    const { scene, ar } = render(Int32Array.from([4021, 4022, 4021, 55555]))
    expect(_bondMesh(scene).count).toBe(1)
    ar.dispose?.()
  })

  it('draws no bond mesh at all when the topology is missing — the old NAMD symptom', () => {
    const { scene, ar } = render([])
    expect(_bondMesh(scene)).toBeUndefined()
    // Spheres still render: this was exactly what a live NAMD run used to look like.
    expect(scene.children.filter((o) => o.isInstancedMesh).length).toBeGreaterThan(0)
    ar.dispose?.()
  })
})

// ── Per-cluster colour + opacity ──────────────────────────────────────────────
// Keyed per NUCLEOTIDE (`helix:bp:dir`), not per strand. The bug that forced this: a
// strand can pass through several clusters and the scaffold passes through nearly all
// of them, so a strand-keyed lookup painted every scaffold atom with whichever cluster
// owned its first domain — the scaffold inside Cluster 3 came out Cluster 4's colour.

function twoNucScene() {
  const scene = new THREE.Scene()
  const ar = initAtomisticRenderer(scene)
  ar.setMode('ballstick')
  ar.update({
    atoms: [
      // Same STRAND, different nucleotides — the case strand-keying got wrong.
      { serial: 0, element: 'P', helix_id: 'hA', bp_index: 5, direction: 'FORWARD',
        strand_id: 'scaffold', x: 0, y: 0, z: 0 },
      { serial: 1, element: 'P', helix_id: 'hB', bp_index: 9, direction: 'FORWARD',
        strand_id: 'scaffold', x: 0.15, y: 0, z: 0 },
    ],
    bonds: [[0, 1]],
  })
  return { scene, ar }
}
const KA = 'hA:5:FORWARD'
const KB = 'hB:9:FORWARD'
const atomMeshes = (scene) =>
  scene.children.filter(o => o.isInstancedMesh && o.name === 'atomSpheres')
const alphaAt = (mesh, i) => mesh.geometry.getAttribute('instanceAlpha')?.getX(i)
const allAlphas = (scene) => atomMeshes(scene).flatMap(m =>
  Array.from({ length: m.count }, (_, i) => alphaAt(m, i)))
const instColorAt = (mesh, i) => {
  const c = new THREE.Color(); mesh.getColorAt(i, c); return c.getHex()
}
const allColors = (scene) => atomMeshes(scene).flatMap(m =>
  Array.from({ length: m.count }, (_, i) => instColorAt(m, i)))

describe('atomistic per-cluster colour + opacity', () => {
  it('installs NOTHING while nothing is faded', () => {
    const { scene, ar } = twoNucScene()
    ar.setClusterDisplay(new Map())
    for (const m of atomMeshes(scene)) {
      expect(m.geometry.getAttribute('instanceAlpha')).toBeUndefined()
      expect(m.material.transparent).toBe(false)
    }
    ar.dispose()
  })

  it('fades ONE nucleotide of a strand without touching its neighbour', () => {
    // The regression pin. Both atoms share a strand id; only one is in the faded
    // cluster. Strand-keyed resolution could not express this at all.
    const { scene, ar } = twoNucScene()
    ar.setClusterDisplay(new Map([[KA, 0.3]]))
    const seen = allAlphas(scene)
    expect(seen.some(a => Math.abs(a - 0.3) < 1e-6)).toBe(true)
    expect(seen).toContain(1)
    ar.dispose()
  })

  it('colours ONE nucleotide of a strand without touching its neighbour', () => {
    // The reported bug, directly: the scaffold segment inside Cluster 3 must take
    // Cluster 3's colour even though the rest of the same strand is in Cluster 4.
    const { scene, ar } = twoNucScene()
    ar.setClusterDisplay(new Map(), new Map([[KA, 0xff00ff], [KB, 0x00ffcc]]))
    const seen = allColors(scene)
    expect(seen).toContain(0xff00ff)
    expect(seen).toContain(0x00ffcc)
    ar.dispose()
  })

  it('leaves an atom in no cluster on its normal colour', () => {
    const { scene, ar } = twoNucScene()
    ar.setClusterDisplay(new Map(), new Map([[KA, 0xff00ff]]))
    const seen = allColors(scene)
    expect(seen).toContain(0xff00ff)
    expect(seen.some(c => c !== 0xff00ff)).toBe(true)
    ar.dispose()
  })

  it('marks the material transparent so the alpha actually blends', () => {
    const { scene, ar } = twoNucScene()
    ar.setClusterDisplay(new Map([[KA, 0.3]]))
    for (const m of atomMeshes(scene)) expect(m.material.transparent).toBe(true)
    ar.dispose()
  })

  it('fades a BOND to the lower of its two atoms', () => {
    const { scene, ar } = twoNucScene()
    ar.setClusterDisplay(new Map([[KA, 0.3]]))
    expect(alphaAt(_bondMesh(scene), 0)).toBeCloseTo(0.3, 5)
    ar.dispose()
  })

  it('restores every instance to opaque when cleared', () => {
    const { scene, ar } = twoNucScene()
    ar.setClusterDisplay(new Map([[KA, 0.3]]))
    ar.setClusterDisplay(new Map())
    for (const m of atomMeshes(scene)) {
      for (let i = 0; i < m.count; i++) expect(alphaAt(m, i)).toBe(1)
    }
    ar.dispose()
  })

  it('survives a rebuild — the sweep rides _applyColors, which update() calls', () => {
    const { scene, ar } = twoNucScene()
    ar.setClusterDisplay(new Map([[KA, 0.3]]))
    ar.update({
      atoms: [
        { serial: 0, element: 'P', helix_id: 'hA', bp_index: 5, direction: 'FORWARD',
          strand_id: 'scaffold', x: 0, y: 0, z: 0 },
        { serial: 1, element: 'P', helix_id: 'hB', bp_index: 9, direction: 'FORWARD',
          strand_id: 'scaffold', x: 0.15, y: 0, z: 0 },
      ],
      bonds: [[0, 1]],
    })
    expect(allAlphas(scene).some(a => Math.abs(a - 0.3) < 1e-6)).toBe(true)
    ar.dispose()
  })

  it('leaves atoms of unlisted nucleotides opaque', () => {
    const { scene, ar } = twoNucScene()
    ar.setClusterDisplay(new Map([['hZ:0:FORWARD', 0.1]]))
    expect(allAlphas(scene).every(a => a === 1)).toBe(true)
    ar.dispose()
  })
})
