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

// ── Defaults ──────────────────────────────────────────────────────────────────

const DEFAULT_OPACITY    = 0.85
const UNIFORM_COLOR      = 0xC8D8E8   // soft blue-grey, neutral molecular surface

// ── Module ────────────────────────────────────────────────────────────────────

export function initSurfaceRenderer(scene) {
  let _mesh         = null   // THREE.Mesh currently in scene
  let _cachedData   = null   // last data object from API (retains vertex_strand_index*)
  let _colorMode    = 'strand'
  let _opacity      = DEFAULT_OPACITY
  let _mode         = 'off'  // 'off' | 'on' — mirrors _surfaceMode in main.js
  let _liveVerts    = null   // Float32Array reference into the live mesh position buffer
  let _strandHexMap = null   // Map<strand_id, hex> last applied via applyStrandColors

  // ── Geometry builder ────────────────────────────────────────────────────────

  function _buildVertexColorArray(data, strandHexMap) {
    // Prefer a client-side recompute when both the index table and a strand
    // colour map are present — keeps the surface in sync with bead palette,
    // group overrides, and custom strand colours from the current session.
    if (strandHexMap
        && Array.isArray(data.vertex_strand_index_table)
        && Array.isArray(data.vertex_strand_index)) {
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

  function _buildGeometry(data) {
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
    if (_strandHexMap && Array.isArray(_cachedData.vertex_strand_index)) return true
    return !!_cachedData.vertex_colors
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
  function update(data, colorMode) {
    _cachedData = data
    _colorMode  = colorMode ?? _colorMode
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
  function applyStrandColors(strandHexMap) {
    _strandHexMap = strandHexMap instanceof Map ? strandHexMap : null
    if (!_mesh || !_cachedData) return
    const colArr = _buildVertexColorArray(_cachedData, _strandHexMap)
    if (!colArr) return
    _mesh.geometry.setAttribute('color', new THREE.BufferAttribute(colArr, 3))
    if (_colorMode === 'strand' && !_mesh.material.vertexColors) {
      _mesh.material.vertexColors = true
      _mesh.material.color.setHex(0xFFFFFF)
      _mesh.material.needsUpdate = true
    }
  }

  /**
   * Update surface opacity live.
   * @param {number} val - 0.0 to 1.0
   */
  function setOpacity(val) {
    _opacity = val
    if (_mesh) {
      _mesh.material.opacity = val
      _mesh.material.transparent = val < 1.0
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
    _mesh.frustumCulled = false   // surface spans the full design; skip frustum test
    scene.add(_mesh)
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
    } else {
      // Topology mismatch — snap to nearest keyframe state.
      const snapData = t < 0.5 ? fromData : toData
      if (snapData.vertices.length !== _liveVerts?.length) {
        _rebuildTopology(snapData)
      } else {
        const sv = snapData.vertices
        for (let i = 0; i < sv.length; i++) _liveVerts[i] = sv[i]
        _mesh.geometry.attributes.position.needsUpdate = true
      }
    }
  }

  /**
   * Replace the live geometry buffer with new vertex + face data.
   * Preserves the existing material, but disables vertex colours (baked states
   * do not carry strand colour data).  Normals are recomputed immediately.
   */
  function _rebuildTopology(data) {
    if (!_mesh) return
    const oldGeo   = _mesh.geometry
    const vertsArr = new Float32Array(data.vertices)
    _liveVerts     = vertsArr
    const newGeo   = new THREE.BufferGeometry()
    newGeo.setAttribute('position', new THREE.BufferAttribute(vertsArr, 3))
    newGeo.setIndex(new THREE.BufferAttribute(new Uint32Array(data.faces), 1))
    newGeo.computeVertexNormals()
    // Baked states carry no strand colours — switch to uniform to avoid missing attribute.
    if (_mesh.material.vertexColors) {
      _mesh.material.vertexColors = false
      _mesh.material.color.setHex(UNIFORM_COLOR)
      _mesh.material.needsUpdate = true
    }
    _mesh.geometry = newGeo
    oldGeo.dispose()
  }

  /** Return 'on' when a surface mesh is displayed, 'off' otherwise. */
  function getMode() { return _mode }

  return { update, setColorMode, setOpacity, dispose, applyPositionLerp, getMode, applyStrandColors }
}
