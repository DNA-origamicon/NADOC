/**
 * Proximity crossover markers — thin cylinders that automatically appear at
 * valid staple crossover positions and fade in when the cursor is nearby.
 *
 * Behaviour
 * ---------
 *  • Active whenever a design with geometry is loaded; rebuilds on geometry change.
 *  • Staple-only: positions where either helix carries scaffold are hidden.
 *  • Opacity scales linearly from OPACITY_MIN (cursor far away) to OPACITY_MAX
 *    (cursor within PROXIMITY_PX screen pixels of the cylinder midpoint).
 *  • When the cursor is within HOVER_PX the cylinder turns gold and reaches
 *    full opacity — a click at this point places the crossover.
 *  • Placement calls POST /design/staple-crossover (topological strand split+reconnect).
 *
 * Usage
 * -----
 *   const cm = initCrossoverMarkers(scene, camera, canvas)
 *   // Markers appear automatically as geometry is loaded; no explicit activate needed.
 *   cm.dispose()   // removes all Three.js objects and event listeners
 */

import * as THREE from 'three'
import { store } from '../state/store.js'
import * as api from '../api/client.js'

const CYLINDER_RADIUS = 0.045          // nm
const COLOR_DEFAULT   = new THREE.Color(0x00ccff)  // cyan
const COLOR_HOVER     = new THREE.Color(0xffcc00)  // gold
const OPACITY_MIN     = 0.05
const OPACITY_MAX     = 0.70
const PROXIMITY_PX    = 100   // px — fade-in starts within this radius
const HOVER_PX        = 40    // px — highlight + click threshold

// Shared geometry; individual materials per cylinder for independent opacity.
const _CYL_GEO = new THREE.CylinderGeometry(CYLINDER_RADIUS, CYLINDER_RADIUS, 1, 6)

export function initCrossoverMarkers(scene, camera, canvas) {
  const _group = new THREE.Group()
  scene.add(_group)

  /** @type {Array<{mesh: THREE.Mesh, midpoint: number[], data: object}>} */
  let _markers    = []
  let _mouse      = { x: -99999, y: -99999 }   // canvas-relative screen px
  let _hoveredIdx = -1

  // ── Helpers ────────────────────────────────────────────────────────────────

  function _clear() {
    _group.clear()
    for (const m of _markers) m.mesh.material.dispose()
    _markers    = []
    _hoveredIdx = -1
  }

  /** Build a cylinder mesh between two world-space backbone positions. */
  function _buildMesh(posA, posB) {
    const vA  = new THREE.Vector3(...posA)
    const vB  = new THREE.Vector3(...posB)
    const dir = new THREE.Vector3().subVectors(vB, vA)
    const len = dir.length()
    if (len < 1e-6) return null

    const mat  = new THREE.MeshPhongMaterial({
      color:       COLOR_DEFAULT.clone(),
      opacity:     OPACITY_MIN,
      transparent: true,
      depthWrite:  false,
    })
    const mesh = new THREE.Mesh(_CYL_GEO, mat)

    // Place at midpoint, orient along direction, scale to correct length.
    mesh.position.copy(vA).addScaledVector(dir.clone().normalize(), len * 0.5)
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize())
    mesh.scale.y = len
    return mesh
  }

  // ── Refresh ────────────────────────────────────────────────────────────────

  async function _refresh() {
    _clear()
    const geometry = store.getState().currentGeometry
    if (!geometry || !geometry.length) return

    const pairs = await api.getAllValidCrossovers()
    if (!pairs) return

    for (const pair of pairs) {
      const { helix_a_id, helix_b_id, positions } = pair
      for (const pos of positions) {
        if (pos.is_scaffold_a || pos.is_scaffold_b) continue

        const nucA = geometry.find(n =>
          n.helix_id === helix_a_id &&
          n.bp_index === pos.bp_a   &&
          n.direction === pos.direction_a
        )
        const nucB = geometry.find(n =>
          n.helix_id === helix_b_id &&
          n.bp_index === pos.bp_b   &&
          n.direction === pos.direction_b
        )
        if (!nucA || !nucB) continue

        const posA = nucA.backbone_position
        const posB = nucB.backbone_position
        const mesh = _buildMesh(posA, posB)
        if (!mesh) continue

        const midpoint = [
          (posA[0] + posB[0]) * 0.5,
          (posA[1] + posB[1]) * 0.5,
          (posA[2] + posB[2]) * 0.5,
        ]
        _group.add(mesh)
        _markers.push({
          mesh,
          midpoint,
          data: {
            helix_a_id, bp_a: pos.bp_a, direction_a: pos.direction_a,
            helix_b_id, bp_b: pos.bp_b, direction_b: pos.direction_b,
          },
        })
      }
    }
  }

  // ── Proximity / opacity ────────────────────────────────────────────────────

  /** Project a world position to canvas-relative screen coordinates. */
  function _toScreen(worldXYZ) {
    const v    = new THREE.Vector3(...worldXYZ).project(camera)
    const rect = canvas.getBoundingClientRect()
    return {
      x: (v.x *  0.5 + 0.5) * rect.width,
      y: (v.y * -0.5 + 0.5) * rect.height,
    }
  }

  function _updateOpacities() {
    let closestDist = Infinity
    let closestIdx  = -1

    for (let i = 0; i < _markers.length; i++) {
      const sp = _toScreen(_markers[i].midpoint)
      const d  = Math.hypot(sp.x - _mouse.x, sp.y - _mouse.y)
      if (d < closestDist) { closestDist = d; closestIdx = i }

      const t   = Math.max(0, 1 - d / PROXIMITY_PX)
      const mat = _markers[i].mesh.material
      mat.opacity = OPACITY_MIN + (OPACITY_MAX - OPACITY_MIN) * t
      mat.color.copy(COLOR_DEFAULT)
    }

    // Clear previous hover highlight.
    if (_hoveredIdx >= 0 && _hoveredIdx < _markers.length) {
      _markers[_hoveredIdx].mesh.material.color.copy(COLOR_DEFAULT)
    }

    _hoveredIdx = (closestDist <= HOVER_PX) ? closestIdx : -1

    if (_hoveredIdx >= 0) {
      const mat   = _markers[_hoveredIdx].mesh.material
      mat.color.copy(COLOR_HOVER)
      mat.opacity = OPACITY_MAX
    }
  }

  // ── Event handlers ─────────────────────────────────────────────────────────

  function _onMouseMove(e) {
    const rect = canvas.getBoundingClientRect()
    _mouse.x   = e.clientX - rect.left
    _mouse.y   = e.clientY - rect.top
    if (_markers.length) _updateOpacities()
  }

  async function _onClick(e) {
    if (e.button !== 0 || _hoveredIdx < 0) return
    const { data } = _markers[_hoveredIdx]

    const result = await api.addStapleCrossover({
      helixAId:   data.helix_a_id,
      bpA:        data.bp_a,
      directionA: data.direction_a,
      helixBId:   data.helix_b_id,
      bpB:        data.bp_b,
      directionB: data.direction_b,
    })
    if (!result) {
      const err = store.getState().lastError
      console.error('Staple crossover placement failed:', err?.message)
    }
    // On success the store's currentGeometry changes → _refresh() is called
    // automatically by the subscription below.
  }

  canvas.addEventListener('mousemove', _onMouseMove)
  window.addEventListener('pointerup', _onClick)

  // Rebuild whenever the geometry changes (new extrusion, undo, redo, etc.)
  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry !== prevState.currentGeometry) {
      _refresh()
    }
  })

  function dispose() {
    canvas.removeEventListener('mousemove', _onMouseMove)
    window.removeEventListener('pointerup', _onClick)
    _clear()
    scene.remove(_group)
  }

  // isActive() always returns false — this system has no explicit active mode;
  // it is always on. The Escape handler in main.js checks this so it can fall
  // through to close the slice plane instead.
  return { dispose, isActive: () => false }
}
