/**
 * md_solvent_overlay.js — explicit water and ions from a NAMD run.
 *
 * Two draw styles, chosen by the scene representation (`md_display_state.solventRepMode`):
 *   'sphere'    — one sphere per water molecule, at its oxygen (full / beads reps)
 *   'atomistic' — the real O + 2 H, with O–H sticks in ball-and-stick (vdw / ballstick)
 * Ions are always simple spheres, coloured and sized by species.
 *
 * ── Why this is not `initMdOverlay` ──────────────────────────────────────────
 * Two properties of solvent make the bead overlay the wrong tool:
 *
 * 1. **The molecule count changes every frame.** A hydration shell is a distance
 *    query and water diffuses, so frame N and frame N+1 hold different molecules in
 *    different numbers (measured on a real 10hb run: 20 595 then 19 837 at 5 Å).
 *    `md_overlay.js` rebuilds its InstancedMesh whenever the count changes, which
 *    here would mean a full reallocation on every single frame. This module
 *    allocates with headroom and only ever moves `mesh.count`.
 *
 * 2. **It must SNAP, never lerp.** Interpolating between two different molecule
 *    sets is meaningless — molecule *i* of frame N is not molecule *i* of frame N+1.
 *    This is the opposite of the DNA path's `applyPositionLerp`.
 *
 * Counts are large (10^4–10^6 spheres), so this uses the impostor path when it is
 * enabled: a 2-triangle billboard instead of a ~160-triangle sphere. No picking
 * raycast is installed — solvent is not selectable, and the impostor raycast is
 * O(count) JS per pick.
 */

import * as THREE from 'three'

import { ELEMENTS, BALL_RADIUS, BOND_RADIUS } from './atomistic_renderer/atom_palette.js'
import {
  CYLINDER_GEO, createGeometryState, bondMatrix,
  atomSphereGeometry, makeAtomSphereMaterial, atomInstanceScale,
} from './atomistic_renderer/geometry_builder.js'

/**
 * Per-species display. Radii are deliberately NOT the bare ionic radii:
 *  - Mg is drawn oversized because the sphere stands in for the whole hexahydrate
 *    complex (the backend keeps the ion's six waters on the water toggle), and
 *    because it separates Mg from Cl, whose CPK greens are close.
 *  - Na/Cl use their CPK colours so they read the same as in any other viewer.
 * Index = the species code on the wire (md_solvent.SPECIES) — append only.
 */
export const ION_STYLE = [
  { name: 'Na⁺', color: 0xAB5CF2, radius: 0.120 },
  { name: 'Cl⁻', color: 0x1FF01F, radius: 0.170 },
  { name: 'Mg²⁺', color: 0x8AFF00, radius: 0.300 },
  { name: 'K⁺',  color: 0x8F40D4, radius: 0.150 },
  { name: 'Ca²⁺', color: 0x3DFF00, radius: 0.200 },
]

/** Sphere-mode water: roughly the O van der Waals radius, in a soft blue so the
 *  bath reads as water and stays distinct from the violet Na+ condensed on the DNA.
 *  (Atomistic mode uses real CPK per element instead — red O, white H.) */
const WATER_SPHERE_RADIUS = 0.140
const WATER_SPHERE_COLOR = 0x5aa9e6

/** Spare capacity when a mesh has to grow, so a slowly-swelling shell doesn't
 *  reallocate every frame. */
const GROWTH = 1.25

/**
 * How many instances to allocate for `n`. Grow-only with headroom; never shrink,
 * because shrinking on a dip just guarantees another reallocation on the next rise.
 */
export function capacityFor(n, current = 0) {
  if (n <= current) return current
  return Math.max(1, Math.ceil(n * GROWTH))
}

export function initMdSolventOverlay(scene) {
  const _geom = createGeometryState()
  const _matCache = new Map()
  const _meshes = new Map()      // key → { mesh, capacity }
  let _mode = 'off'              // 'off' | 'sphere' | 'atomistic'
  let _ballstick = false         // draw O–H sticks (ball-and-stick, not VDW)
  let _waterVisible = true
  let _ionsVisible = true
  let _stats = { nWater: 0, nIons: 0 }
  let _ionSpecies = null

  // Materials are cached for the same reason atomistic_renderer caches them: an
  // impostor material carries a unique customProgramCacheKey, so a fresh one per
  // frame would be a fresh SHADER PROGRAM per frame.
  function _material(key, make) {
    let m = _matCache.get(key)
    if (!m) { m = make(); _matCache.set(key, m) }
    return m
  }

  function _sphereMesh(key, radius, n, withColor, color = 0xffffff) {
    let entry = _meshes.get(key)
    const capacity = capacityFor(n, entry?.capacity ?? 0)
    if (!entry || capacity > entry.capacity) {
      if (entry) { scene.remove(entry.mesh); entry.mesh.dispose() }
      const mesh = new THREE.InstancedMesh(
        atomSphereGeometry(),
        _material(`s|${key}|${radius.toFixed(4)}|${color}`,
          () => { const m = makeAtomSphereMaterial(radius); m.color.setHex(color); return m }),
        capacity,
      )
      mesh.name = 'mdSolvent'
      mesh.userData.solventKey = key
      mesh.frustumCulled = false
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
      if (withColor) {
        mesh.instanceColor =
          new THREE.InstancedBufferAttribute(new Float32Array(capacity * 3), 3)
      }
      scene.add(mesh)
      entry = { mesh, capacity }
      _meshes.set(key, entry)
    }
    entry.mesh.count = n
    entry.mesh.visible = n > 0
    return entry.mesh
  }

  function _bondMesh(n) {
    let entry = _meshes.get('bonds')
    const capacity = capacityFor(n, entry?.capacity ?? 0)
    if (!entry || capacity > entry.capacity) {
      if (entry) { scene.remove(entry.mesh); entry.mesh.dispose() }
      const mesh = new THREE.InstancedMesh(
        CYLINDER_GEO,
        _material('bond', () => new THREE.MeshStandardMaterial({
          color: 0xdddddd, roughness: 0.6, transparent: true, opacity: 0.85,
        })),
        capacity,
      )
      mesh.name = 'mdSolvent'
      mesh.userData.solventKey = 'bonds'
      mesh.frustumCulled = false
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
      scene.add(mesh)
      entry = { mesh, capacity }
      _meshes.set('bonds', entry)
    }
    entry.mesh.count = n
    entry.mesh.visible = n > 0
    return entry.mesh
  }

  function _hide(key) {
    const e = _meshes.get(key)
    if (e) { e.mesh.count = 0; e.mesh.visible = false }
  }

  function _writeSpheres(mesh, xyz, n, stride, offset, scale) {
    const m = _geom.tmpMat
    for (let i = 0; i < n; i++) {
      const o = i * stride + offset
      m.identity()
      m.makeScale(scale, scale, scale)
      m.setPosition(xyz[o], xyz[o + 1], xyz[o + 2])
      mesh.setMatrixAt(i, m)
    }
    mesh.instanceMatrix.needsUpdate = true
  }

  function _drawWater(frame) {
    const n = _waterVisible ? (frame.nWater | 0) : 0
    if (!n || _mode === 'off') { _hide('waterO'); _hide('waterH'); _hide('bonds'); return }
    const xyz = frame.water

    if (_mode === 'sphere') {
      _hide('waterH'); _hide('bonds')
      const r = WATER_SPHERE_RADIUS
      _writeSpheres(_sphereMesh('waterO', r, n, false, WATER_SPHERE_COLOR),
        xyz, n, 3, 0, atomInstanceScale(r))
      return
    }

    // Atomistic: O and both H, from the 9-float O,H,H record.
    const rO = _ballstick ? BALL_RADIUS : ELEMENTS.O.vdw
    const rH = _ballstick ? BALL_RADIUS * 0.75 : ELEMENTS.H.vdw
    _writeSpheres(_sphereMesh('waterO', rO, n, false, ELEMENTS.O.color),
      xyz, n, 9, 0, atomInstanceScale(rO))

    const hMesh = _sphereMesh('waterH', rH, n * 2, false, ELEMENTS.H.color)
    const hScale = atomInstanceScale(rH)
    const m = _geom.tmpMat
    for (let i = 0; i < n; i++) {
      const o = i * 9
      for (let k = 0; k < 2; k++) {
        const p = o + 3 + k * 3
        m.identity()
        m.makeScale(hScale, hScale, hScale)
        m.setPosition(xyz[p], xyz[p + 1], xyz[p + 2])
        hMesh.setMatrixAt(i * 2 + k, m)
      }
    }
    hMesh.instanceMatrix.needsUpdate = true

    if (!_ballstick) { _hide('bonds'); return }
    const bonds = _bondMesh(n * 2)
    for (let i = 0; i < n; i++) {
      const o = i * 9
      for (let k = 0; k < 2; k++) {
        const p = o + 3 + k * 3
        const bm = bondMatrix(_geom, xyz[o], xyz[o + 1], xyz[o + 2],
          xyz[p], xyz[p + 1], xyz[p + 2], BOND_RADIUS)
        if (bm) bonds.setMatrixAt(i * 2 + k, bm)
      }
    }
    bonds.instanceMatrix.needsUpdate = true
  }

  function _drawIons(frame) {
    const n = _ionsVisible ? (frame.ions.length / 3) | 0 : 0
    if (!n || _mode === 'off') {
      for (let s = 0; s < ION_STYLE.length; s++) _hide(`ion${s}`)
      return
    }
    // ONE MESH PER SPECIES, not one mesh with per-instance colour+scale.
    //
    // Under impostors the painted radius is a material UNIFORM, so a single mesh
    // could only ever draw one radius — every ion would come out Mg-sized. Species
    // are few (≤5, so ≤5 draw calls) and their counts are static, so bucketing is
    // both cheaper to think about and correct in the impostor and real-sphere paths
    // alike. Colour then rides the material too, and no instanceColor is needed.
    const buckets = new Map()
    for (let i = 0; i < n; i++) {
      const s = _ionSpecies?.[i] ?? 0
      const k = s < ION_STYLE.length ? s : 0
      let arr = buckets.get(k)
      if (!arr) { arr = []; buckets.set(k, arr) }
      arr.push(i)
    }
    const m = _geom.tmpMat
    for (let s = 0; s < ION_STYLE.length; s++) {
      const rows = buckets.get(s)
      if (!rows?.length) { _hide(`ion${s}`); continue }
      const sp = ION_STYLE[s]
      const mesh = _sphereMesh(`ion${s}`, sp.radius, rows.length, false, sp.color)
      const scale = atomInstanceScale(sp.radius)
      for (let i = 0; i < rows.length; i++) {
        const o = rows[i] * 3
        m.identity()
        m.makeScale(scale, scale, scale)
        m.setPosition(frame.ions[o], frame.ions[o + 1], frame.ions[o + 2])
        mesh.setMatrixAt(i, m)
      }
      mesh.instanceMatrix.needsUpdate = true
    }
  }

  return {
    /**
     * @param {'off'|'sphere'|'atomistic'} mode
     * @param {boolean} ballstick draw O–H sticks (ball-and-stick rather than VDW)
     */
    setMode(mode, ballstick = false) {
      _mode = mode
      _ballstick = !!ballstick
      if (mode === 'off') this.clear()
    },

    getMode() { return _mode },

    /** Species codes for the ion instances — static for a job, set once per load. */
    setIonSpecies(codes) { _ionSpecies = codes ?? null },

    /**
     * Draw one frame. SNAPS: solvent is never interpolated between frames, because
     * the molecule set itself differs (see the module header).
     * @param {{water:Float32Array, nWater:number, ions:Float32Array}} frame
     */
    setFrame(frame) {
      if (!frame || _mode === 'off') { this.clear(); return }
      _drawWater(frame)
      _drawIons(frame)
      _stats = { nWater: _waterVisible ? (frame.nWater | 0) : 0,
                 nIons: _ionsVisible ? (frame.ions.length / 3) | 0 : 0 }
    },

    setWaterVisible(v) { _waterVisible = !!v; if (!v) { _hide('waterO'); _hide('waterH'); _hide('bonds') } },
    setIonsVisible(v) {
      _ionsVisible = !!v
      if (!v) for (let s = 0; s < ION_STYLE.length; s++) _hide(`ion${s}`)
    },

    stats() {
      return {
        ..._stats,
        capacity: Object.fromEntries(
          [..._meshes].map(([k, e]) => [k, e.capacity])),
      }
    },

    /** Hide everything, keeping the allocated meshes for the next frame. */
    clear() {
      for (const key of _meshes.keys()) _hide(key)
      _stats = { nWater: 0, nIons: 0 }
    },

    dispose() {
      for (const { mesh } of _meshes.values()) { scene.remove(mesh); mesh.dispose() }
      _meshes.clear()
      for (const m of _matCache.values()) m.dispose()
      _matCache.clear()
      _ionSpecies = null
      _stats = { nWater: 0, nIons: 0 }
    },
  }
}
