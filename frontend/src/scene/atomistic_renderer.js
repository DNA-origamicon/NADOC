/**
 * Atomistic renderer — Phase AA.
 *
 * Renders the heavy-atom all-atom model using one THREE.InstancedMesh per
 * element type (P, C, N, O — 4 draw calls total).
 *
 * Two display modes:
 *   'vdw'      — Space-filling: sphere radius = Van der Waals radius.  No bonds.
 *   'ballstick' — Ball-and-stick: small sphere (0.07 nm) + bond cylinders.
 *
 * Selection highlighting (mirrors the coarse-grained bead model):
 *   strand     — all atoms on the selected strand → white; others → dimmed CPK
 *   domain     — atoms on matching helix+direction within the strand → white;
 *                rest of strand → 40% CPK; other strands → 15% CPK
 *   nucleotide — atoms at the selected bp → white; same domain → 55% CPK;
 *                rest of strand → 30% CPK; others → 15% CPK
 *   multi-lasso — atoms in any selected strand_id → white; others → dimmed CPK
 *   (no selection) — all atoms at full CPK colour
 *
 * Usage:
 *   const ar = initAtomisticRenderer(scene)
 *   ar.update(atomData)                        // atomData = GET /api/design/atomistic
 *   ar.setMode('vdw')                          // 'vdw' | 'ballstick' | 'off'
 *   ar.highlight(selectedObject, multiIds)     // call on store change
 *   ar.dispose()
 */

import * as THREE from 'three'

import { ELEMENTS, DEFAULT_ELEMENT, BALL_RADIUS, BOND_RADIUS } from './atomistic_renderer/atom_palette.js'
import {
  SPHERE_GEO, CYLINDER_GEO, createGeometryState,
  atomOffset, sphereMatrix, bondMatrix,
  makeSphereMaterial, makeBondMaterial,
} from './atomistic_renderer/geometry_builder.js'
import { resolveAtomColor } from './atomistic_renderer/color_resolver.js'

let _colorMode    = 'cpk'    // 'cpk' | 'strand' | 'base'
let _vdwScale     = 1.0      // multiplier on VdW / ball radii
let _strandColors = new Map()  // strand_id → hex number (used when _colorMode==='strand')
let _baseColors   = new Map()  // "strand_id:bp_index:direction" → hex (used when _colorMode==='base')
let _scalarColors = null       // "helix:bp:dir" → hex; oxDNA flexibility-map overlay (null = off)

// Spurious-bond guard for position overlays (applyPositionLerp) — now a BACKSTOP,
// not the primary fix. The oxDNA→atomistic reconstruction stamps each nucleotide by
// its own relaxed rigid frame (a1/a3) and covers loop/insertion copies, so the
// long cross-structure bonds it used to hide no longer occur in the normal path.
// This cutoff stays only to absorb a pathological frame (e.g. a stranded atom from a
// design whose insertion copies a future code path doesn't yet frame): real DNA
// bonds are ≤~0.2 nm, so any bond longer than this is HIDDEN (zero-scale instance)
// rather than drawn as a line spanning the structure.
const _MAX_BOND_NM = 1.0
const _HIDDEN_BOND = new THREE.Matrix4().makeScale(0, 0, 0)

// ── Renderer factory ──────────────────────────────────────────────────────────

export function initAtomisticRenderer(scene) {

  // Factory-scoped mutable state bundled into one object per Pass 13-F's
  // closure-capture decomposition. The `geom` field holds THREE scratch
  // buffers + shared axis constants so geometry_builder.js helpers can reuse
  // them (allocation-avoidance contract intact).
  const _state = {
    scene,
    elementMeshes:  {},   // { P: InstancedMesh, C: …, N: …, O: … }
    elementAtoms:   {},   // { P: atom[], … } — instance order
    elementRadius:  {},   // { P: r, … } — sphere radius at t=0
    bondMesh:       null,
    bondAtomPairs:  [],   // [{a, b}] matching bond instance order
    mode:           'off',
    lastData:       null,
    // Last highlight params — re-applied after rebuild so mode-switch preserves colour.
    lastSel:        null,
    lastMulti:      [],
    geom:           createGeometryState(),
  }

  // ── Cleanup ──────────────────────────────────────────────────────────────

  function _clearScene() {
    for (const mesh of Object.values(_state.elementMeshes)) {
      _state.scene.remove(mesh)
      mesh.material.dispose()
    }
    _state.elementMeshes = {}
    _state.elementAtoms  = {}
    _state.elementRadius = {}
    if (_state.bondMesh) {
      _state.scene.remove(_state.bondMesh)
      _state.bondMesh.material.dispose()
      _state.bondMesh = null
    }
    _state.bondAtomPairs = []
  }

  // ── Rebuild geometry ──────────────────────────────────────────────────────

  function _rebuild(data) {
    _clearScene()
    if (_state.mode === 'off' || !data?.atoms?.length) return

    const atoms = data.atoms
    const bonds = data.bonds ?? []
    const isVdw = _state.mode === 'vdw'

    // Bucket atoms by element, preserving order for instance mapping. A bucket
    // is created lazily for any element present (including protein elements like
    // S not in the base DNA catalogue); unknown elements fall back to a grey
    // default rather than being silently dropped.
    const buckets = {}
    for (const atom of atoms) {
      (buckets[atom.element] ??= []).push(atom)
    }

    for (const [el, group] of Object.entries(buckets)) {
      if (!group.length) continue
      const meta = ELEMENTS[el] ?? DEFAULT_ELEMENT
      const radius = (isVdw ? meta.vdw : BALL_RADIUS) * _vdwScale
      const mesh   = new THREE.InstancedMesh(SPHERE_GEO, makeSphereMaterial(), group.length)
      mesh.frustumCulled = false
      // Enable per-instance colour (initialised to white; _applyColors sets them)
      mesh.instanceColor = new THREE.InstancedBufferAttribute(
        new Float32Array(group.length * 3), 3
      )
      group.forEach((atom, i) => mesh.setMatrixAt(i, sphereMatrix(_state.geom, atom.x, atom.y, atom.z, radius)))
      mesh.instanceMatrix.needsUpdate = true
      _state.scene.add(mesh)
      _state.elementMeshes[el] = mesh
      _state.elementAtoms[el]  = group
      _state.elementRadius[el] = radius
    }

    // Bond cylinders
    if (!isVdw && bonds.length) {
      const bySerial = []
      for (const atom of atoms) bySerial[atom.serial] = atom
      const pairs    = []
      const matrices = []
      for (const [i, j] of bonds) {
        const a = bySerial[i]; const b = bySerial[j]
        if (!a || !b) continue
        const m = bondMatrix(_state.geom, a.x, a.y, a.z, b.x, b.y, b.z, BOND_RADIUS)
        if (m) { matrices.push(m); pairs.push({ a, b }) }
      }
      if (matrices.length) {
        const bm = new THREE.InstancedMesh(CYLINDER_GEO, makeBondMaterial(), matrices.length)
        bm.frustumCulled = false
        bm.instanceColor = new THREE.InstancedBufferAttribute(
          new Float32Array(matrices.length * 3), 3,
        )
        matrices.forEach((m, i) => bm.setMatrixAt(i, m))
        bm.instanceMatrix.needsUpdate = true
        _state.scene.add(bm)
        _state.bondMesh      = bm
        _state.bondAtomPairs = pairs
      }
    }

    // Re-apply last known highlight state after geometry rebuild
    _applyColors(_state.lastSel, _state.lastMulti)
  }

  // ── Colour application ────────────────────────────────────────────────────

  // Build a per-call snapshot of module-mutable colour state for color_resolver.
  // The resolver is pure — it only reads `colorMode`, `strandColors`, `baseColors`
  // through this ctx, never closes over the module-level let-bindings directly.
  // Extracting `_colorMode` / `_strandColors` / `_baseColors` themselves is
  // Pass 14+ scope per Pass 12-B's surface map.
  function _colorCtx() {
    return { colorMode: _colorMode, strandColors: _strandColors, baseColors: _baseColors,
             scalarColors: _scalarColors }
  }

  function _applyColors(sel, multiIds) {
    const hasSelection = sel != null || multiIds.length > 0
    const tColor = _state.geom.tColor
    const ctx    = _colorCtx()
    for (const [el, mesh] of Object.entries(_state.elementMeshes)) {
      const group = _state.elementAtoms[el]
      let dirty   = false
      for (let i = 0; i < group.length; i++) {
        const hex = resolveAtomColor(ctx, group[i], sel, multiIds, hasSelection)
        tColor.setHex(hex)
        mesh.setColorAt(i, tColor)
        dirty = true
      }
      if (dirty && mesh.instanceColor) mesh.instanceColor.needsUpdate = true
    }
    // Bond cylinders — colour each half of the cylinder isn't supported by
    // a single instance, so just paint each bond with its first atom's colour.
    // For intra-strand / intra-residue bonds (the common case) the two atoms
    // share strand_id and bp_index, so the result matches the connecting balls.
    if (_state.bondMesh && _state.bondAtomPairs.length) {
      for (let i = 0; i < _state.bondAtomPairs.length; i++) {
        const { a } = _state.bondAtomPairs[i]
        const hex = resolveAtomColor(ctx, a, sel, multiIds, hasSelection)
        tColor.setHex(hex)
        _state.bondMesh.setColorAt(i, tColor)
      }
      if (_state.bondMesh.instanceColor) _state.bondMesh.instanceColor.needsUpdate = true
    }
  }

  // ── Public API ────────────────────────────────────────────────────────────

  return {
    /** Load new atom data and rebuild scene objects. */
    update(data) {
      _state.lastData = data
      _rebuild(data)
    },

    /**
     * Raycast the rendered atoms. Returns the closest hit's atom (+ distance)
     * or null. Used for click-to-select; the atom's `helix_id` carries the
     * protein sentinel `__protein__{attachmentId}`.
     */
    raycastPick(raycaster) {
      const meshes = Object.values(_state.elementMeshes)
      if (!meshes.length) return null
      const hits = raycaster.intersectObjects(meshes, false)
      if (!hits.length) return null
      const hit = hits[0]
      // Find which element bucket this mesh is, then map instanceId → atom.
      for (const [el, mesh] of Object.entries(_state.elementMeshes)) {
        if (mesh === hit.object) {
          const atom = _state.elementAtoms[el]?.[hit.instanceId]
          return atom ? { atom, distance: hit.distance } : null
        }
      }
      return null
    },

    /** Centroid of all currently-rendered atoms (world nm), or null. */
    centroidOf(predicate = null) {
      let n = 0; let x = 0; let y = 0; let z = 0
      for (const [, group] of Object.entries(_state.elementAtoms)) {
        for (const a of group) {
          if (predicate && !predicate(a)) continue
          x += a.x; y += a.y; z += a.z; n++
        }
      }
      return n ? { x: x / n, y: y / n, z: z / n } : null
    },

    /**
     * Snapshot the instances matching `predicate` so a live rigid transform can
     * be previewed without a server round-trip (used by the gizmo during drag).
     */
    beginLiveTransform(predicate) {
      const items = []
      for (const [el, group] of Object.entries(_state.elementAtoms)) {
        for (let i = 0; i < group.length; i++) {
          if (predicate(group[i])) {
            const a = group[i]
            items.push({ el, idx: i, x: a.x, y: a.y, z: a.z })
          }
        }
      }
      _state.live = items
    },

    /** Apply a THREE.Matrix4 to the snapshotted instances (preview, per frame). */
    applyLiveTransform(mat4) {
      if (!_state.live?.length) return
      const v = new THREE.Vector3()
      const touched = new Set()
      for (const it of _state.live) {
        const mesh = _state.elementMeshes[it.el]
        if (!mesh) continue
        v.set(it.x, it.y, it.z).applyMatrix4(mat4)
        mesh.setMatrixAt(it.idx, sphereMatrix(_state.geom, v.x, v.y, v.z, _state.elementRadius[it.el]))
        touched.add(mesh)
      }
      for (const mesh of touched) mesh.instanceMatrix.needsUpdate = true
    },

    /** End the live-transform preview (next update() rebuilds authoritatively). */
    endLiveTransform() { _state.live = null },

    /**
     * Apply per-protein relaxed-pose transforms for the OxDNA display: each
     * attachment's atoms (helix_id `__protein__{attachmentId}`) are rewritten by
     * its rigid 4×4.  `transforms` = { [attachmentId]: number[16] } (ROW-MAJOR, as
     * the backend emits); pass null/empty to restore every protein to its design
     * pose (from cached coords).
     */
    applyOxdnaTransforms(transforms) {
      const PFX = '__protein__'
      const mats = {}
      for (const id in (transforms || {})) {
        const arr = transforms[id]
        if (Array.isArray(arr) && arr.length === 16) mats[id] = new THREE.Matrix4().set(...arr)
      }
      const v = new THREE.Vector3()
      const touched = new Set()
      for (const [el, group] of Object.entries(_state.elementAtoms)) {
        const mesh = _state.elementMeshes[el]
        if (!mesh) continue
        for (let i = 0; i < group.length; i++) {
          const a = group[i]
          const sid = (typeof a.helix_id === 'string' && a.helix_id.startsWith(PFX))
            ? a.helix_id.slice(PFX.length) : null
          const m = sid ? mats[sid] : null
          v.set(a.x, a.y, a.z)
          if (m) v.applyMatrix4(m)
          mesh.setMatrixAt(i, sphereMatrix(_state.geom, v.x, v.y, v.z, _state.elementRadius[el]))
          touched.add(mesh)
        }
      }
      for (const mesh of touched) mesh.instanceMatrix.needsUpdate = true
    },

    /** Restore every protein to its design pose (clear OxDNA-display transforms). */
    clearOxdnaTransforms() { this.applyOxdnaTransforms(null) },

    /**
     * Switch display mode: 'off' | 'vdw' | 'ballstick'.
     * Re-uses cached atom data; no refetch.
     */
    setMode(mode) {
      if (mode === _state.mode) return
      _state.mode = mode
      _rebuild(_state.lastData)
    },

    getMode() { return _state.mode },

    /**
     * Apply selection highlight.
     * Call whenever store.selectedObject or store.multiSelectedStrandIds changes.
     *
     * @param {object|null} selectedObject  — store.selectedObject
     * @param {string[]}    multiIds        — store.multiSelectedStrandIds (default [])
     */
    highlight(selectedObject, multiIds = []) {
      _state.lastSel   = selectedObject
      _state.lastMulti = multiIds
      _applyColors(selectedObject, multiIds)
    },

    /** Remove all scene objects and free GPU memory. */
    dispose() {
      _clearScene()
      _state.lastData = null
    },

    /** Set VdW / ball radius scale (1.0 = standard). Rebuilds geometry. */
    setVdwScale(scale) {
      _vdwScale = scale
      _rebuild(_state.lastData)
    },

    /**
     * Set atom colouring mode.
     *
     *   'cpk'    — per-element CPK.  Strand colours still apply to extra-base
     *              atoms (aux_helix_id), so always pass the strand map.
     *   'strand' — strandColors is the primary lookup (also used for 'cluster',
     *              just with a cluster-keyed map).
     *   'base'   — baseColors keyed by "strand_id:bp_index:direction"; atoms
     *              without a letter fall back to strandColors then CPK.
     *
     * @param {'cpk'|'strand'|'base'} mode
     * @param {Map<string,number>} strandColors  strand_id → hex
     * @param {Map<string,number>|null} baseColors  base position key → hex
     */
    setColorMode(mode, strandColors = new Map(), baseColors = null) {
      _colorMode    = mode
      _strandColors = strandColors instanceof Map ? strandColors : new Map()
      if (baseColors instanceof Map) _baseColors = baseColors
      _applyColors(_state.lastSel, _state.lastMulti)
    },

    /**
     * Overlay a scalar colour map (e.g. the oxDNA flexibility map) keyed by
     * "helix:bp:dir" → hex.  When set and nothing is selected, each atom takes its
     * nucleotide's colour, so ball-and-stick / VdW shows the same rigid→flexible
     * ramp as the beads.  Accepts a Map or a plain object; repaints in place.
     */
    applyScalarColors(map) {
      _scalarColors = map instanceof Map ? map
        : (map && typeof map === 'object' ? new Map(Object.entries(map)) : null)
      _applyColors(_state.lastSel, _state.lastMulti)
    },

    /** Drop the scalar overlay → atoms return to CPK/strand/base colouring. */
    clearScalarColors() {
      if (!_scalarColors) return
      _scalarColors = null
      _applyColors(_state.lastSel, _state.lastMulti)
    },

    /**
     * Shift atom positions by per-helix lateral offsets (Q expanded view).
     *
     * Each atom is displaced by lerp(offsets[helix_id], offsets[aux_helix_id], aux_t) * t.
     * Extra-crossover-base atoms (aux_helix_id set) interpolate between the two
     * junction helices proportionally to their position along the bridge.
     *
     * @param {Map<string, THREE.Vector3>} offsets  helix_id → world-space offset at t=1
     * @param {number}                     t        animation parameter 0→1
     */
    applyUnfoldOffsets(offsets, t) {
      const _tmpP = new THREE.Vector3()
      const tmpMat = _state.geom.tmpMat

      // Spheres
      for (const [el, mesh] of Object.entries(_state.elementMeshes)) {
        const group  = _state.elementAtoms[el]
        const radius = _state.elementRadius[el] ?? BALL_RADIUS
        let dirty = false
        for (let i = 0; i < group.length; i++) {
          const atom = group[i]
          const off  = atomOffset(_state.geom, atom, offsets, t)
          _tmpP.set(atom.x + off.x, atom.y + off.y, atom.z + off.z)
          tmpMat.identity()
          tmpMat.makeScale(radius, radius, radius)
          tmpMat.setPosition(_tmpP.x, _tmpP.y, _tmpP.z)
          mesh.setMatrixAt(i, tmpMat)
          dirty = true
        }
        if (dirty) mesh.instanceMatrix.needsUpdate = true
      }

      // Bond cylinders
      if (_state.bondMesh && _state.bondAtomPairs.length) {
        for (let i = 0; i < _state.bondAtomPairs.length; i++) {
          const { a, b } = _state.bondAtomPairs[i]
          const offA = atomOffset(_state.geom, a, offsets, t)
          const offB = atomOffset(_state.geom, b, offsets, t)
          const m = bondMatrix(
            _state.geom,
            a.x + offA.x, a.y + offA.y, a.z + offA.z,
            b.x + offB.x, b.y + offB.y, b.z + offB.z,
            BOND_RADIUS,
          )
          if (m) _state.bondMesh.setMatrixAt(i, m)
        }
        _state.bondMesh.instanceMatrix.needsUpdate = true
      }
    },

    /**
     * Lerp atom positions between two pre-baked position arrays.
     * Called by the animation player each frame to animate deformations.
     *
     * For atoms in a cluster (helix_id in clusterHelixIds), a rigid-body rotation
     * is applied instead of linear lerp to avoid chord-path artifacts during rotation.
     * The formula matches CG applyClusterTransform: new_pos = incrRot(base - center) + dummy,
     * where base is the play-start position (baseXyz).
     *
     * @param {number[]}         fromXyz          flat xyz indexed by serial — from-keyframe
     * @param {number[]}         toXyz            flat xyz indexed by serial — to-keyframe
     * @param {number}           t                lerp fraction 0→1
     * @param {number[]|null}    [baseXyz]        play-start xyz (rigid-body base for clusters)
     * @param {Array}            [clusterTransforms]  [{helix_ids, center, dummy, incrRot}, ...]
     * @param {Set<string>|null} [clusterHelixIds]    set of helix IDs in any cluster
     */
    applyPositionLerp(fromXyz, toXyz, t, baseXyz = null, clusterTransforms = [], clusterHelixIds = null) {
      if (!fromXyz || !toXyz) return

      // Build helix_id → cluster transform lookup for O(1) per-atom access.
      const helixClusterMap = new Map()
      if (clusterHelixIds && baseXyz && clusterTransforms.length) {
        for (const ct of clusterTransforms) {
          for (const hid of ct.helix_ids) helixClusterMap.set(hid, ct)
        }
      }

      const _tmpV = new THREE.Vector3()
      const tmpMat = _state.geom.tmpMat

      /**
       * Compute the display position for one atom.
       * Cluster atoms: rigid-body rotation applied to play-start (base) position.
       * Others: linear lerp between from and to.
       */
      function _atomXYZ(helix_id, serial) {
        const s  = serial * 3
        const ct = helixClusterMap.get(helix_id)
        if (ct && baseXyz) {
          // Rigid body: rotate (base_pos − center) by incrRot, translate to dummy.
          _tmpV.set(baseXyz[s] - ct.center.x, baseXyz[s + 1] - ct.center.y, baseXyz[s + 2] - ct.center.z)
          _tmpV.applyQuaternion(ct.incrRot)
          return [_tmpV.x + ct.dummy.x, _tmpV.y + ct.dummy.y, _tmpV.z + ct.dummy.z]
        }
        // Linear lerp for non-cluster atoms.
        return [
          fromXyz[s]     + (toXyz[s]     - fromXyz[s])     * t,
          fromXyz[s + 1] + (toXyz[s + 1] - fromXyz[s + 1]) * t,
          fromXyz[s + 2] + (toXyz[s + 2] - fromXyz[s + 2]) * t,
        ]
      }

      for (const [el, mesh] of Object.entries(_state.elementMeshes)) {
        const group  = _state.elementAtoms[el]
        const radius = _state.elementRadius[el] ?? BALL_RADIUS
        let dirty = false
        for (let i = 0; i < group.length; i++) {
          const atom    = group[i]
          const [x, y, z] = _atomXYZ(atom.helix_id, atom.serial)
          tmpMat.identity()
          tmpMat.makeScale(radius, radius, radius)
          tmpMat.setPosition(x, y, z)
          mesh.setMatrixAt(i, tmpMat)
          dirty = true
        }
        if (dirty) mesh.instanceMatrix.needsUpdate = true
      }

      if (_state.bondMesh && _state.bondAtomPairs.length) {
        for (let i = 0; i < _state.bondAtomPairs.length; i++) {
          const { a, b } = _state.bondAtomPairs[i]
          const [ax, ay, az] = _atomXYZ(a.helix_id, a.serial)
          const [bx, by, bz] = _atomXYZ(b.helix_id, b.serial)
          const dx = bx - ax, dy = by - ay, dz = bz - az
          if (dx * dx + dy * dy + dz * dz > _MAX_BOND_NM * _MAX_BOND_NM) {
            _state.bondMesh.setMatrixAt(i, _HIDDEN_BOND)   // over-stretched → hide, don't span the model
            continue
          }
          const m = bondMatrix(_state.geom, ax, ay, az, bx, by, bz, BOND_RADIUS)
          if (m) _state.bondMesh.setMatrixAt(i, m)
        }
        _state.bondMesh.instanceMatrix.needsUpdate = true
      }
    },
  }
}
