/**
 * Atomistic renderer — Phase AA.
 *
 * Renders the heavy-atom all-atom model using one THREE.InstancedMesh per
 * element type (P, C, N, O — 4 draw calls total).
 *
 * Two display modes:
 *   'vdw'      — Space-filling: sphere radius = Van der Waals radius.  No bonds.
 *   'ballstick' — Ball-and-stick: small sphere (0.07 nm) + bond cylinders.
 *   'stick'     — Classic stick: bond cylinders only (no atom spheres).
 *
 * Selection highlighting (mirrors the coarse-grained bead model):
 *   strand     — all atoms on the selected strand → white; others stay unchanged
 *   domain     — atoms on matching helix+direction within the strand → white;
 *                rest of strand → 40% CPK; other strands → 15% CPK
 *   nucleotide — atoms at the selected bp → white; same domain → 55% CPK;
 *                rest of strand → 30% CPK; others → 15% CPK
 *   multi-lasso — atoms in any selected strand_id → white; others stay unchanged
 *   (no selection) — all atoms at full CPK colour
 *
 * Sphere impostors (Phase C, 2026-07-30): when `impostorsEnabled()` each atom
 * mesh is a 2-triangle billboard quad ray-painting a lit sphere instead of a
 * ~160-triangle SphereGeometry — ~80x fewer triangles, which is what makes a
 * solvated all-atom scene renderable at all. Bonds stay real cylinders. The flag
 * is read at REBUILD time, so flipping it mid-session needs an `update()` /
 * `setMode()` / `setVdwScale()` to take effect. See memory/project_sphere_impostors.md.
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
  CYLINDER_GEO, createGeometryState,
  atomOffset, sphereMatrix, bondMatrix,
  makeBondMaterial,
  atomSphereGeometry, makeAtomSphereMaterial, atomInstanceScale,
} from './atomistic_renderer/geometry_builder.js'
import {
  impostorsEnabled,
  installSphereImpostorRaycast,
  enableImpostorInstanceAlpha,
} from './impostor_material.js'
import {
  installInstanceAlpha,
  installInstanceAlphaGeometry,
  setInstanceAlpha,
} from './instance_alpha.js'
import { resolveAtomColor } from './atomistic_renderer/color_resolver.js'
import { makeAtomTable } from './atom_table.js'

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
  // NB `elementAtoms` / `bondAtomIdx` hold ATOM ROW INDICES, not atom objects. The oxDNA
  // display bundle is ~330k atoms; keeping object references here meant ~330k atoms plus
  // ~740k bond-endpoint refs alive per rebuild. Rows are resolved through `_state.atoms`
  // (an AtomTable) which reads columnar typed arrays or a legacy object array alike.
  const _state = {
    scene,
    elementMeshes:  {},   // { P: InstancedMesh, C: …, N: …, O: … }
    elementAtoms:   {},   // { P: Int32Array of atom rows, … } — instance order
    // What goes in the INSTANCE MATRIX — NOT necessarily the sphere radius.
    // Under impostors it is 1 and the material's u_impostorRadius uniform owns
    // the radius; with real unit-sphere geometry it IS the radius. Conflating
    // the two renders every atom at radius² (see geometry_builder's note). The
    // true radius needs no field: it is carried by the material
    // (`userData.impostorRadius`, which shadow_bounds reads) and captured by the
    // raycast closure at build time.
    elementScale:   {},   // { P: s, … }
    matCache:       new Map(),  // `${el}|${radius}` → material; see _material()
    bondMesh:       null,
    bondAtomIdx:    null, // Int32Array [a0,b0,a1,b1,…] atom rows, bond instance order
    // 'helix:bp:dir' → per-cluster opacity (<1 only) and → per-cluster colour.
    // Both are keyed per NUCLEOTIDE rather than per strand: a strand can span several
    // clusters, and the scaffold spans nearly all of them. Empty = nothing to do, and
    // the alpha channel is never installed, so an unstyled design pays nothing.
    nucAlphas:      new Map(),
    clusterColors:  new Map(),
    atoms:          makeAtomTable(null),
    mode:           'off',
    lastData:       null,
    // Last highlight params — re-applied after rebuild so mode-switch preserves colour.
    lastSel:        null,
    lastMulti:      [],
    geom:           createGeometryState(),
  }

  // ── Anchor-halo entries ───────────────────────────────────────────────────

  // One shared scratch pair: glow_layer._writeEntries copies entries[i].pos immediately,
  // and refreshAllGlow re-reads every entry on every simulation frame, so allocating a
  // Vector3 per anchored atom per frame is exactly what must not happen.
  const _glowMat = new THREE.Matrix4()
  const _glowPos = new THREE.Vector3()

  /** A glow entry over ONE atom instance. The mesh is looked up at read time, never
   *  captured, so the entry keeps working across a `_rebuild()` (which replaces every
   *  InstancedMesh) and follows the atom under applyPositionLerp / unfold. */
  function _atomGlowEntry(el, idx, scale) {
    return {
      scale,
      get pos() {
        const mesh = _state.elementMeshes[el]
        if (!mesh || idx >= mesh.count) return _glowPos.set(0, 0, 0)
        mesh.getMatrixAt(idx, _glowMat)
        return _glowPos.setFromMatrixPosition(_glowMat)
      },
    }
  }

  // Observers of "which atoms are on screen" — see onAtomsChanged.
  const _atomsCbs = []
  let _atomsSig = null

  /** Fire the atom-set observers, but only when (mode, atom count, payload kind) really
   *  changed. The live MD path calls update() every frame with an identical signature,
   *  so this is what keeps an O(N-atoms) re-match off the frame loop. */
  function _notifyAtoms() {
    const sig = `${_state.mode}|${_state.atoms.count}|${_state.atoms.columnar}`
    if (sig === _atomsSig) return
    _atomsSig = sig
    for (const cb of _atomsCbs) cb()
  }

  // ── Materials ─────────────────────────────────────────────────────────────

  /**
   * Cached material per (element, radius). The cache is a CORRECTNESS
   * requirement under the impostor flag, not an optimisation: an impostor
   * material carries `customProgramCacheKey = 'impostorPhong_' + uuid`
   * (impostor_material.js) so that its `u_impostorRadius` actually gets bound.
   * A fresh material per rebuild therefore means a fresh SHADER PROGRAM per
   * rebuild — and the live MD display calls `update()` every frame, which would
   * be a shader compile per frame plus an unbounded program-cache leak. With
   * plain MeshStandardMaterials this was invisible (they all share one program).
   */
  function _material(key, make) {
    let mat = _state.matCache.get(key)
    if (!mat) { mat = make(); _state.matCache.set(key, mat) }
    return mat
  }

  function _matchesResidue(atom, target) {
    if (!atom || !target) return false
    if (target.helix_id === '__xb__') {
      return atom.crossover_id === target.crossover_id && atom.extra_base_k === target.k
    }
    return atom.helix_id === target.helix_id && atom.bp_index === target.bp_index &&
      atom.direction === target.direction && Number(atom.copy_k ?? 0) === Number(target.copy ?? 0)
  }

  // ── Cleanup ──────────────────────────────────────────────────────────────

  // Removes meshes; materials survive in `matCache` (see _material) and are
  // freed only by dispose(). `mesh.dispose()` frees the instanceMatrix /
  // instanceColor GPU buffers — it was missing before 2026-07-30, which leaked
  // one buffer pair per rebuild on the per-frame live-display path.
  function _clearScene() {
    for (const mesh of Object.values(_state.elementMeshes)) {
      _state.scene.remove(mesh)
      mesh.dispose()
    }
    _state.elementMeshes = {}
    _state.elementAtoms  = {}
    _state.elementScale  = {}
    if (_state.bondMesh) {
      _state.scene.remove(_state.bondMesh)
      _state.bondMesh.dispose()
      _state.bondMesh = null
    }
    _state.bondAtomIdx = null
  }

  // ── Rebuild geometry ──────────────────────────────────────────────────────

  /** Bonds arrive either as `[[i,j], …]` (JSON producers) or as a flat Uint32Array of
   *  serial pairs (the columnar bundle). Normalise the access, not the storage. */
  function _bondCount(bonds) {
    if (!bonds) return 0
    return ArrayBuffer.isView(bonds) ? (bonds.length >> 1) : bonds.length
  }
  function _bondEnds(bonds, k, out) {
    if (ArrayBuffer.isView(bonds)) { out[0] = bonds[k * 2]; out[1] = bonds[k * 2 + 1] }
    else { const p = bonds[k]; out[0] = p[0]; out[1] = p[1] }
    return out
  }

  function _rebuild(data) {
    _clearScene()
    const table = _state.atoms = makeAtomTable(data)
    if (_state.mode === 'off' || !table.count) { _notifyAtoms(); return }

    const bonds = data.bonds ?? []
    const isVdw = _state.mode === 'vdw'
    const n = table.count

    // Bucket atom ROWS by element, preserving order for instance mapping. A bucket
    // is created lazily for any element present (including protein elements like
    // S not in the base DNA catalogue); unknown elements fall back to a grey
    // default rather than being silently dropped.
    const buckets = {}
    for (let i = 0; i < n; i++) {
      (buckets[table.element(i)] ??= []).push(i)
    }

    const useImpostors = impostorsEnabled()

    // Stick uses the same atom instances as ball-and-stick for picking, lasso,
    // live selection glow, and animated positions.  Its instances are deliberately
    // NOT attached to the scene, so they never render, cast shadows, or enter photo
    // mode; they are CPU-side pick proxies only. Keeping them here is what gives Stick
    // the complete atomistic selection surface without putting the balls back on screen.
    for (const [el, rows] of Object.entries(buckets)) {
      if (!rows.length) continue
      const meta = ELEMENTS[el] ?? DEFAULT_ELEMENT
      const radius = (isVdw ? meta.vdw : BALL_RADIUS) * _vdwScale
      const scale  = atomInstanceScale(radius)
      const mesh   = new THREE.InstancedMesh(
        atomSphereGeometry(),
        _material(`${el}|${radius.toFixed(4)}`, () => makeAtomSphereMaterial(radius)),
        rows.length,
      )
      mesh.frustumCulled = false
      // Named so photo_renderer/mesh_repr.js resolves these by NAME rather than by
      // material class — under impostors the material is Phong, which its
      // MeshStandardMaterial inference would misread as the 'full' representation.
      mesh.name = 'atomSpheres'
      mesh.userData.element = el
      // Enable per-instance colour (initialised to white; _applyColors sets them)
      mesh.instanceColor = new THREE.InstancedBufferAttribute(
        new Float32Array(rows.length * 3), 3
      )
      const group = Int32Array.from(rows)
      for (let i = 0; i < group.length; i++) {
        const a = group[i]
        mesh.setMatrixAt(i, sphereMatrix(_state.geom, table.x(a), table.y(a), table.z(a), scale))
      }
      mesh.instanceMatrix.needsUpdate = true
      // The quad geometry is a flat billboard on the CPU side, so the stock
      // InstancedMesh.raycast would test the un-billboarded quad. Swap in a
      // ray-vs-sphere test against the instance centres.
      if (useImpostors) installSphereImpostorRaycast(mesh, radius)
      if (_state.mode !== 'stick') _state.scene.add(mesh)
      _state.elementMeshes[el] = mesh
      _state.elementAtoms[el]  = group
      _state.elementScale[el]  = scale
    }

    // Bond cylinders
    const nBonds = _bondCount(bonds)
    if (!isVdw && nBonds) {
      // Bonds reference atom SERIALS. In the columnar format serial IS the row, but a
      // legacy object array can be sparse/reordered, so map serial → row.
      let rowOfSerial = null
      if (!table.columnar) {
        rowOfSerial = new Map()
        for (let i = 0; i < n; i++) rowOfSerial.set(table.serial(i), i)
      }
      const ends = [0, 0]
      const idx = new Int32Array(nBonds * 2)
      const matrices = []
      let kept = 0
      for (let k = 0; k < nBonds; k++) {
        _bondEnds(bonds, k, ends)
        const ra = rowOfSerial ? rowOfSerial.get(ends[0]) : ends[0]
        const rb = rowOfSerial ? rowOfSerial.get(ends[1]) : ends[1]
        if (ra === undefined || rb === undefined || ra >= n || rb >= n) continue
        const m = bondMatrix(_state.geom,
          table.x(ra), table.y(ra), table.z(ra),
          table.x(rb), table.y(rb), table.z(rb), BOND_RADIUS)
        if (!m) continue
        matrices.push(m)
        idx[kept * 2] = ra; idx[kept * 2 + 1] = rb
        kept++
      }
      if (kept) {
        // Bonds stay real cylinders under impostors (Phase C v1 scope).
        const bm = new THREE.InstancedMesh(
          CYLINDER_GEO, _material('bond', makeBondMaterial), kept)
        bm.frustumCulled = false
        bm.name = 'atomBonds'
        bm.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(kept * 3), 3)
        for (let i = 0; i < kept; i++) bm.setMatrixAt(i, matrices[i])
        bm.instanceMatrix.needsUpdate = true
        _state.scene.add(bm)
        _state.bondMesh    = bm
        _state.bondAtomIdx = idx.subarray(0, kept * 2)
      }
    }

    // Re-apply last known highlight state after geometry rebuild
    _applyColors(_state.lastSel, _state.lastMulti)
    _notifyAtoms()
  }

  // ── Colour application ────────────────────────────────────────────────────

  // Build a per-call snapshot of module-mutable colour state for color_resolver.
  // The resolver is pure — it only reads `colorMode`, `strandColors`, `baseColors`
  // through this ctx, never closes over the module-level let-bindings directly.
  // Extracting `_colorMode` / `_strandColors` / `_baseColors` themselves is
  // Pass 14+ scope per Pass 12-B's surface map.
  function _colorCtx() {
    return { colorMode: _colorMode, strandColors: _strandColors, baseColors: _baseColors,
             scalarColors: _scalarColors, clusterColors: _state.clusterColors }
  }

  function _applyColors(sel, multiIds) {
    const hasSelection = sel != null || multiIds.length > 0
    const tColor = _state.geom.tColor
    const ctx    = _colorCtx()
    const table  = _state.atoms
    for (const [el, mesh] of Object.entries(_state.elementMeshes)) {
      const group = _state.elementAtoms[el]
      let dirty   = false
      for (let i = 0; i < group.length; i++) {
        // table.get() may be a shared flyweight — resolveAtomColor reads it and returns
        // a number, so it never outlives this call. See atom_table.js.
        const hex = resolveAtomColor(ctx, table.get(group[i]), sel, multiIds, hasSelection)
        tColor.setHex(hex)
        mesh.setColorAt(i, tColor)
        dirty = true
      }
      if (dirty && mesh.instanceColor) mesh.instanceColor.needsUpdate = true
      if (_state.nucAlphas.size) {
        _ensureAtomAlpha(mesh)
        for (let i = 0; i < group.length; i++) {
          setInstanceAlpha(mesh, i, _alphaOfRow(group[i]))
        }
      }
    }
    // Bond cylinders — colour each half of the cylinder isn't supported by
    // a single instance, so just paint each bond with its first atom's colour.
    // For intra-strand / intra-residue bonds (the common case) the two atoms
    // share strand_id and bp_index, so the result matches the connecting balls.
    const bidx = _state.bondAtomIdx
    if (_state.bondMesh && bidx?.length) {
      for (let i = 0; i < bidx.length / 2; i++) {
        const hex = resolveAtomColor(ctx, table.get(bidx[i * 2]), sel, multiIds, hasSelection)
        tColor.setHex(hex)
        _state.bondMesh.setColorAt(i, tColor)
      }
      if (_state.bondMesh.instanceColor) _state.bondMesh.instanceColor.needsUpdate = true
      if (_state.nucAlphas.size) {
        _ensureAtomAlpha(_state.bondMesh)
        for (let i = 0; i < bidx.length / 2; i++) {
          // A bond spanning two clusters takes the LOWER alpha, so a bond into a
          // faded cluster fades with it rather than hanging on at full strength.
          setInstanceAlpha(_state.bondMesh, i,
            Math.min(_alphaOfRow(bidx[i * 2]), _alphaOfRow(bidx[i * 2 + 1])))
        }
      }
    }
  }

  /** Per-cluster opacity of one atom row, keyed per nucleotide. Atoms carry no
   *  domain_index but they do carry helix + bp + direction, which
   *  color_util.buildNucClusterIndex walks the design's domains to resolve. */
  function _alphaOfRow(row) {
    const a = _state.atoms?.get(row)
    if (!a) return 1
    // Bare-helix fallback covers geometry on synthetic `__ext_` helices, whose per-bp
    // keys are not enumerable from the design.
    return _state.nucAlphas.get(`${a.helix_id}:${a.bp_index}:${a.direction}`)
      ?? _state.nucAlphas.get(a.helix_id) ?? 1
  }

  /** Install the per-instance alpha channel, routing impostor materials through
   *  their own composed patch — applyInstanceAlphaMaterial ASSIGNS onBeforeCompile,
   *  which on an impostor would wipe the billboard + gl_FragDepth patch. Lazy: a
   *  design with nothing faded never flips these materials to transparent. */
  function _ensureAtomAlpha(mesh) {
    if (!mesh || mesh._instanceAlpha) return
    if (mesh.material?.userData?.isImpostor) {
      if (installInstanceAlphaGeometry(mesh)) enableImpostorInstanceAlpha(mesh.material)
    } else {
      installInstanceAlpha(mesh)
    }
  }

  // Optional CPD weld overlay (scene/cpd_weld_overlay.js). It is driven from inside
  // applyPositionLerp so its markers are computed from the SAME placement that positions
  // the atom instances — see the note there.
  let _weldOverlay = null

  // ── Public API ────────────────────────────────────────────────────────────

  return {
    /** Attach (or detach, with null) the CPD weld overlay. */
    setWeldOverlay(overlay) { _weldOverlay = overlay || null },

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
          const row = _state.elementAtoms[el]?.[hit.instanceId]
          // materialize (not get) — this reference escapes to selection_manager/main.js
          // and must not be a flyweight that the next iteration re-points.
          return row === undefined ? null
            : { atom: _state.atoms.materialize(row), distance: hit.distance }
        }
      }
      return null
    },

    /**
     * Visit every currently rendered atom at its actual, live instance position.
     * The position object is scratch storage and must not escape the callback.
     * Selection/lasso uses this instead of the source atom coordinates because
     * unfold, relaxation, and live transforms can move instance matrices.
     */
    visitAtoms(visitor) {
      if (typeof visitor !== 'function' || _state.mode === 'off') return
      const pos = new THREE.Vector3()
      const mat = new THREE.Matrix4()
      for (const [el, group] of Object.entries(_state.elementAtoms)) {
        const mesh = _state.elementMeshes[el]
        if (!mesh?.visible) continue
        for (let i = 0; i < group.length; i++) {
          mesh.getMatrixAt(i, mat)
          pos.setFromMatrixPosition(mat)
          visitor(_state.atoms.get(group[i]), pos)
        }
      }
    },

    /** Build live glow entries for all atoms belonging to the supplied nucleotides. */
    selectionAtomEntries(nucs, { scale = 1.35 } = {}) {
      if (_state.mode === 'off' || !nucs?.length) return []
      const keys = new Set()
      const xbaseKeys = new Set()
      for (const n of nucs) {
        if (n.helix_id === '__xb__') xbaseKeys.add(`${n.crossover_id}:${n.k}`)
        else keys.add(`${n.helix_id}:${n.bp_index}:${n.direction}:${Number(n.copy_k ?? n.copy ?? 0)}`)
      }
      const out = []
      const table = _state.atoms
      for (const [el, group] of Object.entries(_state.elementAtoms)) {
        for (let i = 0; i < group.length; i++) {
          const a = table.get(group[i])
          const key = `${a.helix_id}:${a.bp_index}:${a.direction}:${Number(a.copy_k ?? 0)}`
          const xbKey = `${a.crossover_id}:${a.extra_base_k}`
          if (keys.has(key) || xbaseKeys.has(xbKey)) out.push(_atomGlowEntry(el, i, scale))
        }
      }
      return out
    },

    /** Atom rows + centroid for one base_ref target, or null when it is absent. */
    residueInfo(target) {
      const rows = []
      const centroid = new THREE.Vector3()
      for (let r = 0; r < _state.atoms.count; r++) {
        const atom = _state.atoms.get(r)
        if (!_matchesResidue(atom, target)) continue
        rows.push(r)
        centroid.x += _state.atoms.x(r)
        centroid.y += _state.atoms.y(r)
        centroid.z += _state.atoms.z(r)
      }
      if (!rows.length) return null
      centroid.multiplyScalar(1 / rows.length)
      return { rows, centroid }
    },

    /** Preview a world delta on one residue. Passing identity restores source data. */
    applyResidueMatrix(target, matrix) {
      const wanted = new Set(this.residueInfo(target)?.rows ?? [])
      if (!wanted.size) return false
      const transformed = new Map()
      const v = new THREE.Vector3()
      const tmpMat = _state.geom.tmpMat
      for (const [el, mesh] of Object.entries(_state.elementMeshes)) {
        const group = _state.elementAtoms[el]
        const scale = _state.elementScale[el]
        let dirty = false
        for (let i = 0; i < group.length; i++) {
          const row = group[i]
          if (!wanted.has(row)) continue
          v.set(_state.atoms.x(row), _state.atoms.y(row), _state.atoms.z(row)).applyMatrix4(matrix)
          transformed.set(row, v.clone())
          mesh.setMatrixAt(i, sphereMatrix(_state.geom, v.x, v.y, v.z, scale))
          dirty = true
        }
        if (dirty) mesh.instanceMatrix.needsUpdate = true
      }
      const bidx = _state.bondAtomIdx
      if (_state.bondMesh && bidx?.length) {
        for (let i = 0; i < bidx.length / 2; i++) {
          const ra = bidx[i * 2], rb = bidx[i * 2 + 1]
          if (!wanted.has(ra) && !wanted.has(rb)) continue
          const pa = transformed.get(ra) ?? new THREE.Vector3(_state.atoms.x(ra), _state.atoms.y(ra), _state.atoms.z(ra))
          const pb = transformed.get(rb) ?? new THREE.Vector3(_state.atoms.x(rb), _state.atoms.y(rb), _state.atoms.z(rb))
          const m = bondMatrix(_state.geom, pa.x, pa.y, pa.z, pb.x, pb.y, pb.z, BOND_RADIUS)
          _state.bondMesh.setMatrixAt(i, m ?? _HIDDEN_BOND)
        }
        _state.bondMesh.instanceMatrix.needsUpdate = true
      }
      return true
    },

    /**
     * Purple-halo entries for the exact atoms a NAMD anchor set holds.
     *
     * Returns **null** when this renderer cannot serve the request, so the caller can
     * fall back to the coarse per-nucleotide halo:
     *   • the atomistic rep is off, or nothing is loaded yet;
     *   • the payload is the columnar oxDNA bundle, which drops atom `name` by design
     *     (atom_table.js) — `element` alone cannot tell a C1′ from any other carbon;
     *   • the match would exceed `max` (a cluster anchor × all-heavy atoms is a ~20×
     *     multiplier, and these entries are re-read by refreshAllGlow every sim frame).
     *
     * Each entry's `pos` is a LIVE getter reading the instance matrix, mirroring the
     * base-level selection glow: entries survive a rebuild (the mesh is resolved at read
     * time, never captured) and track atoms moving under applyPositionLerp.
     *
     * @param {Map<string, Set<string>|null>} index 'helix:bp:dir' → held atom names,
     *   null meaning all heavy atoms.
     * @returns {Array<{scale:number, pos:THREE.Vector3}>|null}
     */
    anchorAtomEntries(index, { scale = 1.8, max = 20000 } = {}) {
      const table = _state.atoms
      if (_state.mode === 'off' || !table.count || !index?.size) return null
      if (table.columnar) return null                    // no atom names in the bundle
      if (table.get(0)?.name === undefined) return null   // nameless object payload

      const out = []
      for (const [el, group] of Object.entries(_state.elementAtoms)) {
        for (let i = 0; i < group.length; i++) {
          // Read every field before the next get() — the flyweight contract. Invisible
          // on this (object) path, fatal on a columnar one, so keep it correct here.
          const a = table.get(group[i])
          const names = index.get(`${a.helix_id}:${a.bp_index}:${a.direction}`)
          if (names === undefined) continue               // nucleotide not anchored
          if (names !== null && !names.has(a.name)) continue
          if (a.name?.startsWith('H')) continue           // hydrogens are never anchored
          if (out.length >= max) return null
          out.push(_atomGlowEntry(el, i, scale))
        }
      }
      return out
    },

    /** Subscribe to "the atom set or the mode actually changed".  NOT every update():
     *  the live MD display rebuilds every frame with the same atoms, and re-matching an
     *  anchor set against millions of atoms per frame is the one cost that would make
     *  the per-atom halo unaffordable. */
    onAtomsChanged(cb) { if (typeof cb === 'function') _atomsCbs.push(cb) },

    /** Centroid of all currently-rendered atoms (world nm), or null. */
    centroidOf(predicate = null) {
      let n = 0; let x = 0; let y = 0; let z = 0
      const table = _state.atoms
      for (const [, group] of Object.entries(_state.elementAtoms)) {
        for (let i = 0; i < group.length; i++) {
          const r = group[i]
          if (predicate && !predicate(table.get(r))) continue
          x += table.x(r); y += table.y(r); z += table.z(r); n++
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
      const table = _state.atoms
      for (const [el, group] of Object.entries(_state.elementAtoms)) {
        for (let i = 0; i < group.length; i++) {
          const r = group[i]
          if (predicate(table.get(r))) {
            items.push({ el, idx: i, x: table.x(r), y: table.y(r), z: table.z(r) })
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
        mesh.setMatrixAt(it.idx, sphereMatrix(_state.geom, v.x, v.y, v.z, _state.elementScale[it.el]))
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
      const table = _state.atoms
      for (const [el, group] of Object.entries(_state.elementAtoms)) {
        const mesh = _state.elementMeshes[el]
        if (!mesh) continue
        for (let i = 0; i < group.length; i++) {
          const r = group[i]
          const hid = table.helixId(r)
          const sid = (typeof hid === 'string' && hid.startsWith(PFX))
            ? hid.slice(PFX.length) : null
          const m = sid ? mats[sid] : null
          v.set(table.x(r), table.y(r), table.z(r))
          if (m) v.applyMatrix4(m)
          mesh.setMatrixAt(i, sphereMatrix(_state.geom, v.x, v.y, v.z, _state.elementScale[el]))
          touched.add(mesh)
        }
      }
      for (const mesh of touched) mesh.instanceMatrix.needsUpdate = true
    },

    /** Restore every protein to its design pose (clear OxDNA-display transforms). */
    clearOxdnaTransforms() { this.applyOxdnaTransforms(null) },

    /**
     * Switch display mode: 'off' | 'vdw' | 'ballstick' | 'stick'.
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
      for (const mat of _state.matCache.values()) mat.dispose()
      _state.matCache.clear()
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
     *   'cpk'    — per-element CPK, for EVERY atom including crossover extra bases
     *              and extension tails (they used to be pinned to strand colour).
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
     * Per-cluster colour + opacity, both keyed `helix:bp:dir` — per NUCLEOTIDE, because
     * a strand can pass through several clusters and the scaffold passes through nearly
     * all of them. A strand-keyed lookup painted every scaffold atom with whichever
     * cluster owned its first domain. Colour is non-empty only in cluster-coloring mode;
     * opacity applies in every mode. Pass empty maps to clear.
     *
     * Re-applied automatically after a rebuild, because the sweep lives inside
     * _applyColors, which _rebuild already calls.
     * @param {Map<string, number>} alphas    'helix:bp:dir' → alpha
     * @param {Map<string, number>} [colors]  'helix:bp:dir' → packed 0xRRGGBB
     */
    setClusterDisplay(alphas, colors = new Map()) {
      const next       = alphas instanceof Map ? alphas : new Map()
      const nextColors = colors instanceof Map ? colors : new Map()
      const hadColors  = _state.clusterColors.size
      _state.clusterColors = nextColors
      if (!next.size && !_state.nucAlphas.size) {
        // No fade either way — but a colour change still needs a repaint.
        if (hadColors || nextColors.size) _applyColors(_state.lastSel, _state.lastMulti)
        return
      }
      const clearing = !next.size
      _state.nucAlphas = next
      if (clearing) {
        // Restore every installed instance to opaque; the buffers stay installed.
        for (const [el, mesh] of Object.entries(_state.elementMeshes)) {
          const group = _state.elementAtoms[el]
          for (let i = 0; i < group.length; i++) setInstanceAlpha(mesh, i, 1)
        }
        const bidx = _state.bondAtomIdx
        if (_state.bondMesh && bidx?.length) {
          for (let i = 0; i < bidx.length / 2; i++) setInstanceAlpha(_state.bondMesh, i, 1)
        }
      }
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

      const table = _state.atoms

      // Spheres
      for (const [el, mesh] of Object.entries(_state.elementMeshes)) {
        const group = _state.elementAtoms[el]
        const scale = _state.elementScale[el]
        let dirty = false
        for (let i = 0; i < group.length; i++) {
          const r = group[i]
          const off = atomOffset(_state.geom, table.get(r), offsets, t)
          _tmpP.set(table.x(r) + off.x, table.y(r) + off.y, table.z(r) + off.z)
          tmpMat.identity()
          tmpMat.makeScale(scale, scale, scale)
          tmpMat.setPosition(_tmpP.x, _tmpP.y, _tmpP.z)
          mesh.setMatrixAt(i, tmpMat)
          dirty = true
        }
        if (dirty) mesh.instanceMatrix.needsUpdate = true
      }

      // Bond cylinders
      const bidx = _state.bondAtomIdx
      if (_state.bondMesh && bidx?.length) {
        for (let i = 0; i < bidx.length / 2; i++) {
          const ra = bidx[i * 2], rb = bidx[i * 2 + 1]
          // atomOffset returns a fresh Vector3, so reading it after the next get() is
          // safe — but read each row's offset while its flyweight is current.
          const offA = atomOffset(_state.geom, table.get(ra), offsets, t)
          const ax = table.x(ra) + offA.x, ay = table.y(ra) + offA.y, az = table.z(ra) + offA.z
          const offB = atomOffset(_state.geom, table.get(rb), offsets, t)
          const m = bondMatrix(
            _state.geom,
            ax, ay, az,
            table.x(rb) + offB.x, table.y(rb) + offB.y, table.z(rb) + offB.z,
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

      const table = _state.atoms

      for (const [el, mesh] of Object.entries(_state.elementMeshes)) {
        const group = _state.elementAtoms[el]
        const scale = _state.elementScale[el]
        let dirty = false
        for (let i = 0; i < group.length; i++) {
          const r = group[i]
          const [x, y, z] = _atomXYZ(table.helixId(r), table.serial(r))
          tmpMat.identity()
          tmpMat.makeScale(scale, scale, scale)
          tmpMat.setPosition(x, y, z)
          mesh.setMatrixAt(i, tmpMat)
          dirty = true
        }
        if (dirty) mesh.instanceMatrix.needsUpdate = true
      }

      const bidx = _state.bondAtomIdx
      if (_state.bondMesh && bidx?.length) {
        for (let i = 0; i < bidx.length / 2; i++) {
          const ra = bidx[i * 2], rb = bidx[i * 2 + 1]
          const [ax, ay, az] = _atomXYZ(table.helixId(ra), table.serial(ra))
          const [bx, by, bz] = _atomXYZ(table.helixId(rb), table.serial(rb))
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

      // Drive the CPD weld overlay from the SAME placement that just positioned the
      // atoms, so its markers cannot drift off the atoms they annotate.
      //
      // Under an active cluster transform the atoms follow the rigid-body branch, which
      // is keyed by helix_id — an identity the overlay's serial-only pairs cannot supply.
      // Rather than draw at a knowingly wrong position, it is fed nothing and hides
      // itself. MD trajectory display passes no cluster transforms, which is the path
      // this overlay exists for.
      if (_weldOverlay) {
        _weldOverlay.update(
          helixClusterMap.size ? null : (serial) => _atomXYZ(null, serial))
      }
    },
  }
}
