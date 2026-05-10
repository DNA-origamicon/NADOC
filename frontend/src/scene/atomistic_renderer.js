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

import {
  ELEMENTS,
  C_HIGHLIGHT,
  C_DIM_FACTOR,
  _dimColor,
  BALL_RADIUS,
  BOND_RADIUS,
} from './atomistic_renderer/atom_palette.js'

let _colorMode    = 'cpk'    // 'cpk' | 'strand' | 'base'
let _vdwScale     = 1.0      // multiplier on VdW / ball radii
let _strandColors = new Map()  // strand_id → hex number (used when _colorMode==='strand')
let _baseColors   = new Map()  // "strand_id:bp_index:direction" → hex (used when _colorMode==='base')

const _SPHERE_GEO   = new THREE.SphereGeometry(1, 10, 8)
const _CYLINDER_GEO = new THREE.CylinderGeometry(1, 1, 1, 6, 1)

// ── Matrix / colour helpers ───────────────────────────────────────────────────

const _tmpMat = new THREE.Matrix4()
const _tmpQ   = new THREE.Quaternion()
const _tmpS   = new THREE.Vector3()
const _tColor = new THREE.Color()
const _Y_AXIS = new THREE.Vector3(0, 1, 0)
const _ZERO3  = new THREE.Vector3()

/** Interpolated world offset for an atom using aux_helix_id / aux_t. */
function _atomOffset(atom, offsets, t) {
  const base = offsets.get(atom.helix_id) ?? _ZERO3
  if (!atom.aux_helix_id || atom.aux_t === 0) return base.clone().multiplyScalar(t)
  const aux  = offsets.get(atom.aux_helix_id) ?? _ZERO3
  return base.clone().lerp(aux, atom.aux_t).multiplyScalar(t)
}

// Material base colour stays white so that the per-instance colour in
// InstancedBufferAttribute is the final rendered colour (Three.js multiplies
// material.color × instanceColor channel-wise — a non-white base would tint
// every strand/base/cluster colour).
function _sphereMat() {
  return new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.4, metalness: 0.05 })
}

function _bondMat() {
  return new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.6 })
}

function _sphereMatrix(x, y, z, r) {
  _tmpMat.identity()
  _tmpMat.makeScale(r, r, r)
  _tmpMat.setPosition(x, y, z)
  return _tmpMat.clone()
}

function _bondMatrix(ax, ay, az, bx, by, bz, radius) {
  const start = new THREE.Vector3(ax, ay, az)
  const end   = new THREE.Vector3(bx, by, bz)
  const dir   = new THREE.Vector3().subVectors(end, start)
  const len   = dir.length()
  if (len < 1e-9) return null
  const mid = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5)
  _tmpQ.setFromUnitVectors(_Y_AXIS, dir.normalize())
  _tmpS.set(radius, len, radius)
  _tmpMat.compose(mid, _tmpQ, _tmpS)
  return _tmpMat.clone()
}

// ── Renderer factory ──────────────────────────────────────────────────────────

export function initAtomisticRenderer(scene) {

  // Active meshes, keyed by element for fast colour updates.
  // _elementMeshes[el] = InstancedMesh
  // _elementAtoms[el]  = atom[] matching instance order
  let _elementMeshes  = {}   // { P: mesh, C: mesh, N: mesh, O: mesh }
  let _elementAtoms   = {}   // { P: atom[], … }
  let _elementRadius  = {}   // { P: r, … } — sphere radius at t=0
  let _bondMesh       = null
  let _bondAtomPairs  = []   // [{a: atom, b: atom}] matching bond instance order
  let _mode           = 'off'
  let _lastData       = null

  // Last highlight params — re-applied after rebuild so mode-switch preserves colour.
  let _lastSel       = null
  let _lastMulti     = []

  // ── Cleanup ──────────────────────────────────────────────────────────────

  function _clearScene() {
    for (const mesh of Object.values(_elementMeshes)) {
      scene.remove(mesh)
      mesh.geometry.dispose()
      mesh.material.dispose()
    }
    _elementMeshes = {}
    _elementAtoms  = {}
    _elementRadius = {}
    if (_bondMesh) {
      scene.remove(_bondMesh)
      _bondMesh.geometry.dispose()
      _bondMesh.material.dispose()
      _bondMesh = null
    }
    _bondAtomPairs = []
  }

  // ── Rebuild geometry ──────────────────────────────────────────────────────

  function _rebuild(data) {
    _clearScene()
    if (_mode === 'off' || !data?.atoms?.length) return

    const atoms = data.atoms
    const bonds = data.bonds ?? []
    const isVdw = _mode === 'vdw'

    // Bucket atoms by element, preserving order for instance mapping
    const buckets = {}
    for (const el of Object.keys(ELEMENTS)) buckets[el] = []
    for (const atom of atoms) {
      if (buckets[atom.element]) buckets[atom.element].push(atom)
    }

    for (const [el, group] of Object.entries(buckets)) {
      if (!group.length) continue
      const radius = (isVdw ? ELEMENTS[el].vdw : BALL_RADIUS) * _vdwScale
      const mesh   = new THREE.InstancedMesh(_SPHERE_GEO, _sphereMat(), group.length)
      mesh.frustumCulled = false
      // Enable per-instance colour (initialised to white; _applyColors sets them)
      mesh.instanceColor = new THREE.InstancedBufferAttribute(
        new Float32Array(group.length * 3), 3
      )
      group.forEach((atom, i) => mesh.setMatrixAt(i, _sphereMatrix(atom.x, atom.y, atom.z, radius)))
      mesh.instanceMatrix.needsUpdate = true
      scene.add(mesh)
      _elementMeshes[el] = mesh
      _elementAtoms[el]  = group
      _elementRadius[el] = radius
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
        const m = _bondMatrix(a.x, a.y, a.z, b.x, b.y, b.z, BOND_RADIUS)
        if (m) { matrices.push(m); pairs.push({ a, b }) }
      }
      if (matrices.length) {
        const bm = new THREE.InstancedMesh(_CYLINDER_GEO, _bondMat(), matrices.length)
        bm.frustumCulled = false
        bm.instanceColor = new THREE.InstancedBufferAttribute(
          new Float32Array(matrices.length * 3), 3,
        )
        matrices.forEach((m, i) => bm.setMatrixAt(i, m))
        bm.instanceMatrix.needsUpdate = true
        scene.add(bm)
        _bondMesh      = bm
        _bondAtomPairs = pairs
      }
    }

    // Re-apply last known highlight state after geometry rebuild
    _applyColors(_lastSel, _lastMulti)
  }

  // ── Colour application ────────────────────────────────────────────────────

  /**
   * Classify an atom given the current selection and return its colour as 0xRRGGBB.
   *
   * Priority cascade (coarsest to finest):
   *   multi-lasso → strand → domain → nucleotide
   */
  function _colorForAtom(atom, sel, multiIds) {
    const el      = atom.element
    const cpk     = ELEMENTS[el]?.color ?? 0x505050
    const dimCpk  = _dimColor(cpk, C_DIM_FACTOR)

    // Multi-lasso selection overrides everything
    if (multiIds.length > 0) {
      return multiIds.includes(atom.strand_id) ? C_HIGHLIGHT : dimCpk
    }

    if (!sel) return cpk   // no selection — full CPK

    const type = sel.type
    const data = sel.data ?? {}

    if (type === 'strand') {
      return atom.strand_id === data.strand_id ? C_HIGHLIGHT : dimCpk
    }

    if (type === 'domain') {
      if (atom.strand_id !== data.strand_id) return dimCpk
      // Exact domain match: same helix + same direction within the strand
      const inDomain = atom.helix_id  === data.helix_id
                    && atom.direction === data.direction
      return inDomain ? C_HIGHLIGHT : _dimColor(cpk, 0.40)
    }

    if (type === 'nucleotide') {
      if (atom.strand_id !== data.strand_id) return dimCpk
      if (atom.bp_index  === data.bp_index
       && atom.direction === data.direction)       return C_HIGHLIGHT
      // Same strand, same domain (direction match): medium
      if (atom.direction === data.direction)       return _dimColor(cpk, 0.55)
      // Same strand, other domain
      return _dimColor(cpk, 0.30)
    }

    if (type === 'cone') {
      // Cones belong to a strand; highlight that strand
      return atom.strand_id === data.strand_id ? C_HIGHLIGHT : dimCpk
    }

    // base colour by mode; extra-base atoms always use their strand colour
    if (_colorMode === 'strand' || atom.aux_helix_id) {
      return _strandColors.get(atom.strand_id) ?? cpk
    }
    if (_colorMode === 'base') {
      const k = `${atom.strand_id}:${atom.bp_index}:${atom.direction}`
      return _baseColors.get(k) ?? _strandColors.get(atom.strand_id) ?? cpk
    }
    return cpk
  }

  // Resolve the final colour for one atom under the current mode + selection.
  function _resolveAtomColor(atom, sel, multiIds, hasSelection) {
    const el  = atom.element
    const cpk = ELEMENTS[el]?.color ?? 0x505050
    if (hasSelection) return _colorForAtom(atom, sel, multiIds)
    const isXb = !!atom.aux_helix_id  // extra-base: always strand-coloured
    if (_colorMode === 'strand' || isXb) {
      return _strandColors.get(atom.strand_id) ?? cpk
    }
    if (_colorMode === 'base') {
      const k = `${atom.strand_id}:${atom.bp_index}:${atom.direction}`
      return _baseColors.get(k) ?? _strandColors.get(atom.strand_id) ?? cpk
    }
    return cpk
  }

  function _applyColors(sel, multiIds) {
    const hasSelection = sel != null || multiIds.length > 0
    for (const [el, mesh] of Object.entries(_elementMeshes)) {
      const group = _elementAtoms[el]
      let dirty   = false
      for (let i = 0; i < group.length; i++) {
        const hex = _resolveAtomColor(group[i], sel, multiIds, hasSelection)
        _tColor.setHex(hex)
        mesh.setColorAt(i, _tColor)
        dirty = true
      }
      if (dirty && mesh.instanceColor) mesh.instanceColor.needsUpdate = true
    }
    // Bond cylinders — colour each half of the cylinder isn't supported by
    // a single instance, so just paint each bond with its first atom's colour.
    // For intra-strand / intra-residue bonds (the common case) the two atoms
    // share strand_id and bp_index, so the result matches the connecting balls.
    if (_bondMesh && _bondAtomPairs.length) {
      for (let i = 0; i < _bondAtomPairs.length; i++) {
        const { a } = _bondAtomPairs[i]
        const hex = _resolveAtomColor(a, sel, multiIds, hasSelection)
        _tColor.setHex(hex)
        _bondMesh.setColorAt(i, _tColor)
      }
      if (_bondMesh.instanceColor) _bondMesh.instanceColor.needsUpdate = true
    }
  }

  // ── Public API ────────────────────────────────────────────────────────────

  return {
    /** Load new atom data and rebuild scene objects. */
    update(data) {
      _lastData = data
      _rebuild(data)
    },

    /**
     * Switch display mode: 'off' | 'vdw' | 'ballstick'.
     * Re-uses cached atom data; no refetch.
     */
    setMode(mode) {
      if (mode === _mode) return
      _mode = mode
      _rebuild(_lastData)
    },

    getMode() { return _mode },

    /**
     * Apply selection highlight.
     * Call whenever store.selectedObject or store.multiSelectedStrandIds changes.
     *
     * @param {object|null} selectedObject  — store.selectedObject
     * @param {string[]}    multiIds        — store.multiSelectedStrandIds (default [])
     */
    highlight(selectedObject, multiIds = []) {
      _lastSel   = selectedObject
      _lastMulti = multiIds
      _applyColors(selectedObject, multiIds)
    },

    /** Remove all scene objects and free GPU memory. */
    dispose() {
      _clearScene()
      _lastData = null
    },

    /** Set VdW / ball radius scale (1.0 = standard). Rebuilds geometry. */
    setVdwScale(scale) {
      _vdwScale = scale
      _rebuild(_lastData)
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
      _applyColors(_lastSel, _lastMulti)
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

      // Spheres
      for (const [el, mesh] of Object.entries(_elementMeshes)) {
        const group  = _elementAtoms[el]
        const radius = _elementRadius[el] ?? BALL_RADIUS
        let dirty = false
        for (let i = 0; i < group.length; i++) {
          const atom = group[i]
          const off  = _atomOffset(atom, offsets, t)
          _tmpP.set(atom.x + off.x, atom.y + off.y, atom.z + off.z)
          _tmpMat.identity()
          _tmpMat.makeScale(radius, radius, radius)
          _tmpMat.setPosition(_tmpP.x, _tmpP.y, _tmpP.z)
          mesh.setMatrixAt(i, _tmpMat)
          dirty = true
        }
        if (dirty) mesh.instanceMatrix.needsUpdate = true
      }

      // Bond cylinders
      if (_bondMesh && _bondAtomPairs.length) {
        for (let i = 0; i < _bondAtomPairs.length; i++) {
          const { a, b } = _bondAtomPairs[i]
          const offA = _atomOffset(a, offsets, t)
          const offB = _atomOffset(b, offsets, t)
          const m = _bondMatrix(
            a.x + offA.x, a.y + offA.y, a.z + offA.z,
            b.x + offB.x, b.y + offB.y, b.z + offB.z,
            BOND_RADIUS,
          )
          if (m) _bondMesh.setMatrixAt(i, m)
        }
        _bondMesh.instanceMatrix.needsUpdate = true
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

      for (const [el, mesh] of Object.entries(_elementMeshes)) {
        const group  = _elementAtoms[el]
        const radius = _elementRadius[el] ?? BALL_RADIUS
        let dirty = false
        for (let i = 0; i < group.length; i++) {
          const atom    = group[i]
          const [x, y, z] = _atomXYZ(atom.helix_id, atom.serial)
          _tmpMat.identity()
          _tmpMat.makeScale(radius, radius, radius)
          _tmpMat.setPosition(x, y, z)
          mesh.setMatrixAt(i, _tmpMat)
          dirty = true
        }
        if (dirty) mesh.instanceMatrix.needsUpdate = true
      }

      if (_bondMesh && _bondAtomPairs.length) {
        for (let i = 0; i < _bondAtomPairs.length; i++) {
          const { a, b } = _bondAtomPairs[i]
          const [ax, ay, az] = _atomXYZ(a.helix_id, a.serial)
          const [bx, by, bz] = _atomXYZ(b.helix_id, b.serial)
          const m = _bondMatrix(ax, ay, az, bx, by, bz, BOND_RADIUS)
          if (m) _bondMesh.setMatrixAt(i, m)
        }
        _bondMesh.instanceMatrix.needsUpdate = true
      }
    },
  }
}
