/**
 * Surface renderer — VdW and SES molecular surfaces.
 *
 * Renders a triangulated surface mesh returned by GET /api/design/surface.
 * The mesh is built as a single THREE.Mesh with a BufferGeometry (indexed,
 * with computed vertex normals).
 *
 * Supports two colour modes without requiring a re-fetch:
   *   'strand'  — per-vertex RGB colours derived client-side from the response's
   *               vertex_strand_index_table + vertex_strand_index, using the
   *               strand→hex map supplied by applyStrandColors().  Falls back to
   *               the backend-baked vertex_colors when no map is available.
   *   'uniform' — single flat grey material
 *
 * Usage:
   *   const sr = initSurfaceRenderer(scene)
   *   sr.update(data, 'strand')             // data = GET /api/design/surface response
   *   sr.applyStrandColors(strandHexMap)    // recolour without re-fetch
   *   sr.setColorMode('uniform')
   *   sr.setOpacity(0.6)
   *   sr.dispose()
 */

import * as THREE from 'three'
import { applyInstanceAlphaMaterial } from './instance_alpha.js'
import { clusterOfNucKey } from './color_util.js'

// ── Defaults ──────────────────────────────────────────────────────────────────

const DEFAULT_OPACITY    = 0.85
const UNIFORM_COLOR      = 0xC8D8E8   // soft blue-grey, neutral molecular surface

// ── Module ────────────────────────────────────────────────────────────────────

// A per-vertex strand index list may arrive as a plain array (JSON payload) or a
// Uint32Array (binary surface-bin payload) — both index the same way.
const _isIndexable = (a) => Array.isArray(a) || ArrayBuffer.isView(a)

export function initSurfaceRenderer(scene) {
  let _mesh         = null   // THREE.Mesh currently in scene
  let _cachedData   = null   // last data object from API (retains vertex_strand_index*)
  let _colorMode    = 'strand'
  let _opacity      = DEFAULT_OPACITY
  let _mode         = 'off'  // 'off' | 'on' — mirrors _surfaceMode in main.js
  let _liveVerts    = null   // Float32Array reference into the live mesh position buffer
  let _strandHexMap = null   // Map<strand_id, hex> last applied via applyStrandColors
  // Map<strand_id, alpha> — per-cluster opacity. Empty = nothing faded, and the
  // alpha attribute/patch are never installed.
  // Per-cluster display maps. Two key spaces: NUCLEOTIDE (`helix:bp:dir`) when the
  // payload carries the nucleotide table, STRAND otherwise. Both are kept so the choice
  // can be made per payload — an old cached surface still gets the (coarser but
  // correct-for-a-single-cluster) strand-keyed fade.
  let _clusterMaps = { nucColors: null, nucAlphas: null, strandColors: null, strandAlphas: null }

  /** The alpha map matching this payload's identity space. */
  function _alphaMapFor(data) {
    const id = _vertexIdentity(data)
    if (!id) return null
    return id.perNuc ? _clusterMaps.nucAlphas : _clusterMaps.strandAlphas
  }

  /** The cluster-colour map matching this payload's identity space. */
  function _colorMapFor(data) {
    const id = _vertexIdentity(data)
    if (!id) return null
    return id.perNuc ? _clusterMaps.nucColors : _clusterMaps.strandColors
  }
  let _meshName     = 'dna-surface'  // overridable so the region overlay can use a distinct name
  let _crispZones   = false  // crisp per-face strand zones (ChimeraX look) vs Gouraud-blended
  let _crispFaceVert = null  // Int32Array[nFaces]: source vertex whose strand colours each face

  // ── Geometry builder ────────────────────────────────────────────────────────

  /**
   * Per-vertex identity table + index, preferring the NUCLEOTIDE pair over the strand
   *   pair. A strand id cannot resolve per-cluster colour for a strand that spans clusters —
   *   the scaffold spans nearly all of them (LESSONS D15) — so the backend now ships
   *   `helix:bp:direction` per vertex — the design surface and, since 2026-08-02, the
   *   simulation-frame surfaces too. Payloads without it (anything cached from before, or a
   *   producer with no nucleotide identity) transparently fall back to strands.
   *
   * @returns {{table: string[], index: ArrayLike<number>, perNuc: boolean}|null}
   */
  function _vertexIdentity(data) {
    const nt = data?.vertex_nuc_index_table
    const ni = data?.vertex_nuc_index
    if (nt && _isIndexable(ni)) return { table: nt, index: ni, perNuc: true }
    const st = data?.vertex_strand_index_table
    const si = data?.vertex_strand_index
    if (st && _isIndexable(si)) return { table: st, index: si, perNuc: false }
    return null
  }

  function _buildVertexColorArray(data, strandHexMap) {
    // Prefer a client-side recompute when both the index table and a strand
    // colour map are present — keeps the surface in sync with bead palette,
    // group overrides, and custom strand colours from the current session.
    if (strandHexMap
        && Array.isArray(data.vertex_strand_index_table)
        && _isIndexable(data.vertex_strand_index)) {   // plain array (JSON) or Uint32Array (binary)
      const tbl   = data.vertex_strand_index_table
      const idx   = data.vertex_strand_index
      const tblR  = new Float32Array(tbl.length)
      const tblG  = new Float32Array(tbl.length)
      const tblB  = new Float32Array(tbl.length)
      for (let i = 0; i < tbl.length; i++) {
        const hex = strandHexMap.get(tbl[i])
        if (hex == null) {
          // Fallback: try the backend-baked colour for this vertex's first appearance.
          tblR[i] = 0.6; tblG[i] = 0.6; tblB[i] = 0.6
          continue
        }
        tblR[i] = ((hex >> 16) & 0xFF) / 255
        tblG[i] = ((hex >>  8) & 0xFF) / 255
        tblB[i] = ( hex        & 0xFF) / 255
      }
      const out = new Float32Array(idx.length * 3)
      for (let v = 0; v < idx.length; v++) {
        const k = idx[v]
        out[v*3    ] = tblR[k]
        out[v*3 + 1] = tblG[k]
        out[v*3 + 2] = tblB[k]
      }
      return out
    }
    if (data.vertex_colors) return new Float32Array(data.vertex_colors)
    return null
  }

  // Pick the source vertex whose strand id colours a whole face.  Majority of the 3
  // corners (tie-break to the first) → the zone boundary falls on a triangle EDGE
  // instead of being Gouraud-blended across the triangle interior.
  function _chooseFaceVert(idx, i0, i1, i2) {
    const a = idx[i0], b = idx[i1], c = idx[i2]
    if (a === b || a === c) return i0
    if (b === c) return i1
    return i0
  }

  // Per-face strand colours for a NON-INDEXED buffer: all 3 corners of a face get the
  // single colour of that face's chosen strand → flat (crisp) colour zones.  Length =
  // nFaces*3 vertices * 3 channels.  faceVert[f] is the source vertex chosen for face f.
  function _buildCrispColorArray(data, strandHexMap, faceVert) {
    const nFaces = faceVert.length
    const tbl = data.vertex_strand_index_table
    const idx = data.vertex_strand_index
    const baked = data.vertex_colors
    const useMap = strandHexMap && Array.isArray(tbl) && _isIndexable(idx)
    if (!useMap && !baked) return null
    const out = new Float32Array(nFaces * 9)
    for (let f = 0; f < nFaces; f++) {
      const vi = faceVert[f]
      let r = 0.6, g = 0.6, b = 0.6
      if (useMap) {
        const hex = strandHexMap.get(tbl[idx[vi]])
        if (hex != null) {
          r = ((hex >> 16) & 0xFF) / 255
          g = ((hex >>  8) & 0xFF) / 255
          b = ( hex        & 0xFF) / 255
        }
      } else {
        r = baked[vi*3]; g = baked[vi*3 + 1]; b = baked[vi*3 + 2]
      }
      for (let k = 0; k < 3; k++) {
        out[f*9 + k*3] = r; out[f*9 + k*3 + 1] = g; out[f*9 + k*3 + 2] = b
      }
    }
    return out
  }

  // Non-indexed geometry with crisp per-face strand colours but SMOOTH shading: normals
  // are computed on the shared (indexed) mesh and copied to each face corner, so the
  // surface stays rounded while colour boundaries are sharp — ChimeraX's "colour zone" look.
  function _buildCrispGeometry(data) {
    const srcVerts = new Float32Array(data.vertices)
    const faces    = data.faces
    const nFaces   = (faces.length / 3) | 0

    // Smooth per-vertex normals from the shared topology.
    const tmp = new THREE.BufferGeometry()
    tmp.setAttribute('position', new THREE.BufferAttribute(srcVerts, 3))
    tmp.setIndex(new THREE.BufferAttribute(new Uint32Array(faces), 1))
    tmp.computeVertexNormals()
    const srcNormals = tmp.attributes.normal.array
    tmp.dispose()

    const pos = new Float32Array(nFaces * 9)
    const nor = new Float32Array(nFaces * 9)
    const faceVert = new Int32Array(nFaces)
    const idx = _isIndexable(data.vertex_strand_index) ? data.vertex_strand_index : null

    for (let f = 0; f < nFaces; f++) {
      const i0 = faces[f*3], i1 = faces[f*3 + 1], i2 = faces[f*3 + 2]
      faceVert[f] = idx ? _chooseFaceVert(idx, i0, i1, i2) : i0
      const corners = [i0, i1, i2]
      for (let k = 0; k < 3; k++) {
        const vi = corners[k]
        pos[f*9 + k*3] = srcVerts[vi*3]; pos[f*9 + k*3 + 1] = srcVerts[vi*3 + 1]; pos[f*9 + k*3 + 2] = srcVerts[vi*3 + 2]
        nor[f*9 + k*3] = srcNormals[vi*3]; nor[f*9 + k*3 + 1] = srcNormals[vi*3 + 1]; nor[f*9 + k*3 + 2] = srcNormals[vi*3 + 2]
      }
    }

    _crispFaceVert = faceVert
    _liveVerts = pos
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    geo.setAttribute('normal', new THREE.BufferAttribute(nor, 3))   // pre-smoothed; don't recompute
    const colArr = _buildCrispColorArray(data, _strandHexMap, faceVert)
    if (colArr) geo.setAttribute('color', new THREE.BufferAttribute(colArr, 3))
    return geo
  }

  function _buildGeometry(data) {
    _crispFaceVert = null
    if (_crispZones && _colorMode === 'strand' && data.faces?.length) {
      return _buildCrispGeometry(data)
    }
    const geo = new THREE.BufferGeometry()

    const vertsArr = new Float32Array(data.vertices)
    _liveVerts = vertsArr                              // keep reference for in-place lerp
    geo.setAttribute('position', new THREE.BufferAttribute(vertsArr, 3))

    const facesArr = new Uint32Array(data.faces)
    geo.setIndex(new THREE.BufferAttribute(facesArr, 1))

    if (_colorMode === 'strand') {
      const colArr = _buildVertexColorArray(data, _strandHexMap)
      if (colArr) geo.setAttribute('color', new THREE.BufferAttribute(colArr, 3))
    }

    geo.computeVertexNormals()
    return geo
  }

  function _hasVertexColorSource() {
    if (!_cachedData) return false
    if (_strandHexMap && _isIndexable(_cachedData.vertex_strand_index)) return true
    return !!_cachedData.vertex_colors
  }

  /**
   * Per-vertex alpha for per-cluster opacity.
   *
   * The surface is ONE merged mesh with one material, so `material.opacity` is
   * global — the sidebar slider already owns it. Per-cluster fade therefore needs a
   * per-vertex channel, and it reuses the SAME attribute name and SAME shader patch
   * as the instanced meshes: `attribute float instanceAlpha` is a plain per-vertex
   * attribute in GLSL, it is only "per instance" when the buffer is an
   * InstancedBufferAttribute. That reuse is what makes photo mode's re-install work
   * here for free (it keys on `userData.instanceAlphaPatch`).
   *
   * The two multiply in the shader — vertex alpha lands in `diffuseColor.a` at
   * `<color_fragment>`, material opacity is applied after — so a 0.5 cluster inside
   * a 0.8 surface slider reads 0.4, which is what you want.
   *
   * Vertices carry only a STRAND id (`vertex_strand_index_table`), so the map is
   * strand-keyed, matching how strand colour already resolves here.
   */
  function _buildVertexAlphaArray(data, alphaMap) {
    if (!alphaMap?.size) return null
    const id = _vertexIdentity(data)
    if (!id) return null
    const tblA = new Float32Array(id.table.length)
    for (let k = 0; k < id.table.length; k++) {
      tblA[k] = (id.perNuc ? clusterOfNucKey(alphaMap, id.table[k]) : alphaMap.get(id.table[k])) ?? 1
    }
    const out = new Float32Array(id.index.length)
    for (let v = 0; v < id.index.length; v++) out[v] = tblA[id.index[v]]
    return out
  }

  /** Crisp (non-indexed, per-face) twin — one alpha resolved per face, splatted to
   *  its three corners, mirroring _buildCrispColorArray. */
  function _buildCrispAlphaArray(data, alphaMap, faceVert) {
    if (!alphaMap?.size || !faceVert) return null
    const id = _vertexIdentity(data)
    if (!id) return null
    const out = new Float32Array(faceVert.length)
    for (let f = 0; f < faceVert.length / 3; f++) {
      const key = id.table[id.index[faceVert[f * 3]]]
      const a = (id.perNuc ? clusterOfNucKey(alphaMap, key) : alphaMap.get(key)) ?? 1
      out[f * 3] = a; out[f * 3 + 1] = a; out[f * 3 + 2] = a
    }
    return out
  }

  /**
   * Paint per-cluster colour over an already-built vertex-colour array, in place.
   *
   * Overlays rather than replaces because strand/group colour is genuinely per-strand
   * and stays correct; only the cluster tint needs the finer identity. Vertices in no
   * cluster keep whatever the strand pass gave them.
   *
   * NOTE: crisp mode splats one colour per FACE (3 consecutive entries), so the array is
   * indexed by the same faceVert order `_buildCrispColorArray` used, not by vertex.
   */
  function _overlayClusterColors(colArr) {
    const map = _colorMapFor(_cachedData)
    if (!map?.size) return
    const id = _vertexIdentity(_cachedData)
    if (!id) return
    const crisp = _crispZones && _colorMode === 'strand' && _crispFaceVert
    const n = colArr.length / 3
    for (let i = 0; i < n; i++) {
      const vert = crisp ? _crispFaceVert[Math.floor(i / 3) * 3] : i
      const k = id.table[id.index[vert]]
      const hex = id.perNuc ? clusterOfNucKey(map, k) : map.get(k)
      if (hex == null) continue
      colArr[i * 3]     = ((hex >> 16) & 0xFF) / 255
      colArr[i * 3 + 1] = ((hex >>  8) & 0xFF) / 255
      colArr[i * 3 + 2] = ( hex        & 0xFF) / 255
    }
  }

  /** Write (or clear) the alpha attribute + its shader patch on the live mesh. */
  function _applyVertexAlpha() {
    if (!_mesh || !_cachedData) return
    const arr = (_crispZones && _colorMode === 'strand' && _crispFaceVert)
      ? _buildCrispAlphaArray(_cachedData, _alphaMapFor(_cachedData), _crispFaceVert)
      : _buildVertexAlphaArray(_cachedData, _alphaMapFor(_cachedData))
    if (!arr) {
      // Cleared: hand every vertex back to opaque rather than dropping the
      // attribute, so the compiled program stays stable.
      const existing = _mesh.geometry.getAttribute('instanceAlpha')
      if (existing) { existing.array.fill(1); existing.needsUpdate = true }
      return
    }
    _mesh.geometry.setAttribute('instanceAlpha', new THREE.BufferAttribute(arr, 1))
    if (!_mesh.material.userData?.instanceAlphaPatch) applyInstanceAlphaMaterial(_mesh.material)
    // The slider's own `transparent = val < 1` would switch blending off at 1.0 and
    // silently kill the per-vertex fade.
    _mesh.material.transparent = true
  }

  function _buildMaterial() {
    const useVertex = (_colorMode === 'strand' && _hasVertexColorSource())
    return new THREE.MeshPhongMaterial({
      color:        useVertex ? 0xFFFFFF : UNIFORM_COLOR,
      vertexColors: useVertex,
      transparent:  true,
      opacity:      _opacity,
      side:         THREE.DoubleSide,
      shininess:    40,
    })
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  /**
   * Build or replace the surface mesh from new API data.
   * @param {object} data  - response from GET /api/design/surface
   * @param {string} colorMode - 'strand' | 'uniform'
   */
  function update(data, colorMode, name) {
    _cachedData = data
    _colorMode  = colorMode ?? _colorMode
    if (name) _meshName = name
    _mode       = data ? 'on' : 'off'
    _replaceMesh()
  }

  /**
   * Switch colour mode in-place.  Does not re-fetch; uses cached vertex data.
   * @param {'strand'|'uniform'} mode
   */
  function setColorMode(mode) {
    if (mode === _colorMode) return
    _colorMode = mode
    if (!_cachedData) return
    _replaceMesh()
  }

  /**
   * Recolour the surface in-place from a strand_id → hex map.
   * Requires the backend to have shipped vertex_strand_index_table +
   * vertex_strand_index in the last update() payload; otherwise falls back to
   * the backend-baked vertex_colors.
   *
   * @param {Map<string, number>|null} strandHexMap
   */
  /**
   * Per-cluster colour + opacity.
   *
   * Takes BOTH key spaces because only the payload knows which one applies: a surface
   * carrying `vertex_nuc_index_table` resolves per NUCLEOTIDE (correct for a strand that
   * spans clusters — the scaffold spans nearly all of them, LESSONS D15), and anything
   * older or without nucleotide identity falls back to the strand-keyed maps.
   *
   * Colour is non-empty only in cluster-coloring mode; opacity applies in every mode.
   *
   * @param {{nucColors?:Map, nucAlphas?:Map, strandColors?:Map, strandAlphas?:Map}} maps
   */
  function applyClusterDisplay(maps = {}) {
    _clusterMaps = {
      nucColors:    maps.nucColors    instanceof Map ? maps.nucColors    : null,
      nucAlphas:    maps.nucAlphas    instanceof Map ? maps.nucAlphas    : null,
      strandColors: maps.strandColors instanceof Map ? maps.strandColors : null,
      strandAlphas: maps.strandAlphas instanceof Map ? maps.strandAlphas : null,
    }
    if (!_mesh || !_cachedData) return
    // applyStrandColors early-returns when there is no colour source at all (no strand
    // map and no baked vertex_colors), so the fade must be applied independently of it.
    applyStrandColors(_strandHexMap)   // re-runs the cluster colour overlay
    _applyVertexAlpha()
  }

  function applyStrandColors(strandHexMap) {
    _strandHexMap = strandHexMap instanceof Map ? strandHexMap : null
    if (!_mesh || !_cachedData) return
    const colArr = (_crispZones && _colorMode === 'strand' && _crispFaceVert)
      ? _buildCrispColorArray(_cachedData, _strandHexMap, _crispFaceVert)
      : _buildVertexColorArray(_cachedData, _strandHexMap)
    if (!colArr) return
    _overlayClusterColors(colArr)
    _mesh.geometry.setAttribute('color', new THREE.BufferAttribute(colArr, 3))
    if (_colorMode === 'strand' && !_mesh.material.vertexColors) {
      _mesh.material.vertexColors = true
      _mesh.material.color.setHex(0xFFFFFF)
      _mesh.material.needsUpdate = true
    }
    _applyVertexAlpha()   // a recolour must not drop the cluster fade
  }

  /**
   * Toggle crisp per-face strand colour zones (ChimeraX "colour zone" look) vs the
   * default Gouraud-blended per-vertex colours.  Crisp mode gives sharp boundaries
   * between strands while keeping smooth shading; the mesh is rebuilt non-indexed, so
   * this is best on the fine ChimeraX-quality surface (small triangles → clean edges).
   * @param {boolean} on
   */
  function setCrispZones(on) {
    on = !!on
    if (on === _crispZones) return
    _crispZones = on
    if (_cachedData) _replaceMesh()
  }

  /**
   * Update surface opacity live.
   * @param {number} val - 0.0 to 1.0
   */
  function setOpacity(val) {
    _opacity = val
    if (!_mesh) return
    const m = _mesh.material
    m.opacity     = val
    // `|| _strandAlphaMap.size` — at slider 1.0 this would otherwise switch blending
    // off entirely and silently discard the per-cluster per-vertex fade.
    m.transparent = val < 1.0 || (_alphaMapFor(_cachedData)?.size ?? 0) > 0
    // Photo-mode MeshPhysicalMaterial carries a `transmission` channel that is
    // independent of opacity; if we don't drive it here, sliders never produce
    // a fully-opaque surface in photo mode (the gummy preset bakes in
    // transmission=0.45).  Zero it at opacity=1, restore the preset target below.
    if (m.isMeshPhysicalMaterial) {
      m.transmission = (val >= 1.0) ? 0 : (m.userData?.presetTransmission ?? 0)
    }
  }

  /**
   * Remove the surface mesh from the scene and free GPU resources.
   */
  function dispose() {
    if (_mesh) {
      scene.remove(_mesh)
      _mesh.geometry.dispose()
      _mesh.material.dispose()
      _mesh = null
    }
    _cachedData = null
    _liveVerts  = null
    _crispFaceVert = null
    _mode       = 'off'
  }

  // ── Internal ────────────────────────────────────────────────────────────────

  function _replaceMesh() {
    // Dispose old mesh
    if (_mesh) {
      scene.remove(_mesh)
      _mesh.geometry.dispose()
      _mesh.material.dispose()
      _mesh = null
    }
    if (!_cachedData) return

    const geo  = _buildGeometry(_cachedData)
    const mat  = _buildMaterial()
    _mesh = new THREE.Mesh(geo, mat)
    _mesh.name = _meshName        // 'dna-surface' (global) or 'dna-surface-region' (overlay)
    _mesh.frustumCulled = false   // surface spans the full design; skip frustum test
    scene.add(_mesh)
    _applyVertexAlpha()           // fresh geometry knows nothing about the fade
  }

  /**
   * Lerp the live mesh vertex positions between two pre-baked surface states.
   * Called by the animation player each frame during playback.
   *
   * @param {{ vertices: number[], faces: number[] }} fromData  from-keyframe mesh
   * @param {{ vertices: number[], faces: number[] }} toData    to-keyframe mesh
   * @param {number} t  lerp fraction 0→1
   *
   * Same-topology (fromData.vertices.length === toData.vertices.length):
   *   Updates vertex positions in-place each frame.  Rebuilds the geometry
   *   buffer first if the live mesh has a different vertex count (topology
   *   changed from the pre-play state).  Vertex normals are NOT recomputed
   *   during animation for performance; restored by update() after playback.
   *
   * Different topology:
   *   Snaps to the from-state for t < 0.5 and to-state for t >= 0.5 by
   *   rebuilding the geometry buffer with the correct vertex+face data.
   *   Material is switched to uniform colour when a topology rebuild happens
   *   (strand colours require baked data we don't have); the full material is
   *   restored when update() is called after playback ends.
   */
  function applyPositionLerp(fromData, toData, t) {
    if (!_mesh || !fromData || !toData) return
    // Record the frame BEFORE any branch below. Only one of the three paths rebuilds
    // topology; the in-place lerp keeps the existing buffers, and it is taken whenever
    // the vertex count happens to match. Without this, `_cachedData` kept describing the
    // DESIGN surface while a simulation frame was on screen, so per-cluster colour and
    // opacity resolved against the wrong identity table — or against none at all.
    const _identityChanged = _cachedData !== toData
    _cachedData = toData
    // Scalar overlay (oxDNA flexibility map): a single colour-baked frame — always
    // rebuild so the per-vertex viridis colours land even if the vertex count
    // happens to match the current mesh (the in-place lerp never touches colour).
    if (toData.scalar) { _rebuildTopology(toData); return }
    const fromV = fromData.vertices
    const toV   = toData.vertices

    if (fromV.length === toV.length) {
      // Same topology — ensure buffer is sized correctly, then lerp in place.
      if (fromV.length !== _liveVerts?.length) _rebuildTopology(fromData)
      const n = _liveVerts.length
      for (let i = 0; i < n; i++) {
        _liveVerts[i] = fromV[i] + (toV[i] - fromV[i]) * t
      }
      _mesh.geometry.attributes.position.needsUpdate = true
      if (_identityChanged) _applyFrameClusterDisplay(toData)
    } else {
      // Topology mismatch — snap to nearest keyframe state.
      const snapData = t < 0.5 ? fromData : toData
      _cachedData = snapData
      if (snapData.vertices.length !== _liveVerts?.length) {
        _rebuildTopology(snapData)
      } else {
        const sv = snapData.vertices
        for (let i = 0; i < sv.length; i++) _liveVerts[i] = sv[i]
        _mesh.geometry.attributes.position.needsUpdate = true
        if (_identityChanged) _applyFrameClusterDisplay(snapData)
      }
    }
  }

  /**
   * Re-apply per-cluster colour + fade for a frame that reused the existing buffers
   * (the in-place lerp path, which never goes through _rebuildTopology).
   *
   * Colour is skipped for a scalar payload — the flexibility map's viridis ramp IS the
   * information there, and a cluster tint would destroy it. Opacity always applies:
   * "colour is mode-gated, opacity is not" is the contract everywhere else.
   */
  function _applyFrameClusterDisplay(data) {
    if (!data.scalar) {
      const colAttr = _mesh.geometry.getAttribute('color')
      if (colAttr && _colorMapFor(data)?.size) {
        _overlayClusterColors(colAttr.array)
        colAttr.needsUpdate = true
      }
    }
    _applyVertexAlpha()
  }

  /**
   * Replace the live geometry buffer with new vertex + face data.
   * Preserves the existing material AND its strand colouring when the baked
   * data carries `vertex_colors` (surface-batch in `color_mode='strand'`
   * mode does). Falls back to uniform grey only when colour data is absent.
   * Normals are recomputed immediately.
   *
   * This is what keeps surface coloring through topology changes during
   * animation preview / video export — both in normal mode and photo mode.
   * Photo mode is identical here because the swapped MeshPhysicalMaterial
   * honours `vertexColors` and the per-vertex `color` attribute the same
   * way MeshPhongMaterial does.
   */
  function _rebuildTopology(data) {
    if (!_mesh) return
    // A SIMULATION frame replaces the mesh wholesale, so this payload — not the design
    // surface — is now what is on screen. Recording it is what lets the per-cluster
    // machinery reach a simulated surface at all: every engine overlay (oxDNA relaxed /
    // RMSF / trajectory, and NAMD through mdViz) funnels through applyPositionLerp, and
    // without this `_cachedData` still described the design surface while the mesh was a
    // sim frame, so applyClusterDisplay / _applyVertexAlpha early-returned or resolved
    // against the wrong identity table.
    _cachedData    = data
    const oldGeo   = _mesh.geometry
    const vertsArr = new Float32Array(data.vertices)
    _liveVerts     = vertsArr
    const newGeo   = new THREE.BufferGeometry()
    newGeo.setAttribute('position', new THREE.BufferAttribute(vertsArr, 3))
    newGeo.setIndex(new THREE.BufferAttribute(new Uint32Array(data.faces), 1))
    newGeo.computeVertexNormals()

    // `scalar` (flexibility map) shows its baked viridis colours regardless of the
    // user's strand/uniform colour mode; otherwise strand colours need strand mode.
    if ((data.scalar || _colorMode === 'strand') && data.vertex_colors) {
      newGeo.setAttribute('color',
        new THREE.BufferAttribute(new Float32Array(data.vertex_colors), 3))
      if (!_mesh.material.vertexColors) {
        _mesh.material.vertexColors = true
        _mesh.material.color.setHex(0xFFFFFF)
        _mesh.material.needsUpdate = true
      }
    } else if (_mesh.material.vertexColors) {
      // No strand colours in this baked state — fall back to uniform so the
      // shader doesn't read a missing attribute.
      _mesh.material.vertexColors = false
      _mesh.material.color.setHex(UNIFORM_COLOR)
      _mesh.material.needsUpdate = true
    }
    _mesh.geometry = newGeo
    oldGeo.dispose()

    // Per-cluster colour + fade, exactly as _replaceMesh does for the design surface.
    _applyFrameClusterDisplay(data)
  }

  /**
   * Recolour the live mesh in place from a per-vertex RGB array (Float 0-1, 3 per
   * vertex) — used by the oxDNA flexibility map so dragging the RMSF scale recolours
   * the surface without a re-fetch.  No-op without a mesh.
   */
  function applyScalarVertexColors(colArr) {
    if (!_mesh || !colArr) return
    const arr = colArr instanceof Float32Array ? colArr : new Float32Array(colArr)
    _mesh.geometry.setAttribute('color', new THREE.BufferAttribute(arr, 3))
    if (!_mesh.material.vertexColors) {
      _mesh.material.vertexColors = true
      _mesh.material.color.setHex(0xFFFFFF)
      _mesh.material.needsUpdate = true
    }
  }

  /** Return 'on' when a surface mesh is displayed, 'off' otherwise. */
  function getMode() { return _mode }

  /** The live THREE.Mesh (for raycasting), or null. */
  function getMesh() { return _mesh }

  /** Strand id at a raycast Face3 (nearest-atom attribution; uses vertex a). */
  function strandIdAt(face) {
    const tbl = _cachedData?.vertex_strand_index_table
    const idx = _cachedData?.vertex_strand_index
    if (!tbl || !idx || !face) return null
    // Crisp mode is non-indexed: face.a is a corner in the expanded buffer, so the
    // face number is a/3 and its strand is the source vertex we chose for that face.
    if (_crispZones && _crispFaceVert) {
      const vi = _crispFaceVert[(face.a / 3) | 0]
      return vi == null ? null : (tbl[idx[vi]] ?? null)
    }
    return tbl[idx[face.a]] ?? null
  }

  return { update, setColorMode, setOpacity, dispose, applyPositionLerp, getMode,
           applyStrandColors, applyClusterDisplay, applyScalarVertexColors, getMesh, strandIdAt, setCrispZones }
}
