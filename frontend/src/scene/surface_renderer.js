/**
 * Surface renderer — VdW and SES molecular surfaces.
 *
 * Renders a triangulated surface mesh returned by GET /api/design/surface.
 * The mesh is built as a single THREE.Mesh with a BufferGeometry (indexed,
 * with computed vertex normals).
 *
 * Supports two colour modes without requiring a re-fetch:
 *   'strand'  — per-vertex RGB colours from the strand palette (backend-computed)
 *   'uniform' — single flat grey material
 *
 * Usage:
 *   const sr = initSurfaceRenderer(scene)
 *   sr.update(data, 'strand')    // data = GET /api/design/surface response
 *   sr.setColorMode('uniform')   // switch colour without re-fetch
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
  let _cachedData   = null   // last data object from API (retains vertex_colors)
  let _colorMode    = 'strand'
  let _opacity      = DEFAULT_OPACITY

  // ── Geometry builder ────────────────────────────────────────────────────────

  function _buildGeometry(data) {
    const geo = new THREE.BufferGeometry()

    const vertsArr = new Float32Array(data.vertices)
    geo.setAttribute('position', new THREE.BufferAttribute(vertsArr, 3))

    const facesArr = new Uint32Array(data.faces)
    geo.setIndex(new THREE.BufferAttribute(facesArr, 1))

    if (_colorMode === 'strand' && data.vertex_colors) {
      const colArr = new Float32Array(data.vertex_colors)
      geo.setAttribute('color', new THREE.BufferAttribute(colArr, 3))
    }

    geo.computeVertexNormals()
    return geo
  }

  function _buildMaterial() {
    const useVertex = (_colorMode === 'strand' && _cachedData?.vertex_colors)
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
    _replaceMesh()
  }

  /**
   * Switch colour mode in-place.  Does not re-fetch; uses cached vertex_colors.
   * @param {'strand'|'uniform'} mode
   */
  function setColorMode(mode) {
    if (mode === _colorMode) return
    _colorMode = mode
    if (!_cachedData) return
    _replaceMesh()
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

  return { update, setColorMode, setOpacity, dispose }
}
