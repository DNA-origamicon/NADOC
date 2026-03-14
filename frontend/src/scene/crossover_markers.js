/**
 * Proximity crossover markers — one thin cylinder per valid staple backbone
 * junction, appearing automatically and fading in when the cursor is nearby.
 *
 * Each cylinder represents a SINGLE backbone jump (half-crossover) from
 * helix_a@bp_a to helix_b@bp_b.  Clicking places exactly that jump via
 * POST /design/half-crossover.  The cylinder disappears once placed.
 *
 * Multiple cylinders may appear for the same helix pair at different bp
 * positions (e.g. bp=10/11 and bp=21/21 for a given pair).  Clicking two
 * cylinders on the same pair forms a DX motif; clicking one forms a single
 * crossover.
 *
 * Why one cylinder per position (not two):
 *   The "companion" 1-bp offset (bp_a±1) is geometrically ~1.27 nm apart —
 *   far outside the valid crossover threshold.  The actual second crossover of
 *   a natural DX motif is ~10 bp away and already appears as its own cylinder.
 *
 * Off-register positions (bp_a ≠ bp_b) are fully valid — they represent
 * staple strands whose backbones are closest at different bp indices due to the
 * relative helix geometry (e.g. 0.449 nm at bp=10/11 vs 0.518 nm at bp=21/21).
 *
 * Behaviour
 * ---------
 *  • Active whenever a design with geometry is loaded; rebuilds on geometry change.
 *  • Staple-only: positions where either helix carries scaffold are hidden.
 *  • Already-placed jumps (half_ab_placed flag from API) are not shown.
 *  • Opacity scales linearly from OPACITY_MIN (cursor far away) to OPACITY_MAX
 *    (cursor within PROXIMITY_PX screen pixels of the cylinder midpoint).
 *  • The single cylinder closest to the cursor turns gold and reaches full
 *    opacity — a click places that backbone jump.
 *
 * Loop prevention (backend):
 *   If the two endpoints are on the same strand AND the jump would close the
 *   strand into a circle, the backend returns 400 and no change occurs.  The
 *   user can nick the strand first to resolve this.
 *
 * Usage
 * -----
 *   const cm = initCrossoverMarkers(scene, camera, canvas)
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

  /**
   * Each entry: { mesh, midpoint: [x,y,z], data: { helixAId, bpA, directionA, helixBId, bpB, directionB } }
   * @type {Array<{mesh: THREE.Mesh, midpoint: number[], data: object}>}
   */
  let _markers    = []
  let _mouse      = { x: -99999, y: -99999 }
  let _hoveredIdx = -1
  let _generation = 0

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

    mesh.position.copy(vA).addScaledVector(dir.clone().normalize(), len * 0.5)
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize())
    mesh.scale.y = len
    return mesh
  }

  // ── Refresh ────────────────────────────────────────────────────────────────

  async function _refresh() {
    const gen = ++_generation
    _clear()
    const geometry = store.getState().currentGeometry
    if (!geometry || !geometry.length) return

    const pairs = await api.getAllValidCrossovers()
    if (gen !== _generation) return   // superseded by a newer refresh
    if (!pairs) return

    // Build a fast lookup: "helix_id|bp_index|direction" → backbone_position
    const nucMap = new Map()
    for (const n of geometry) {
      nucMap.set(`${n.helix_id}|${n.bp_index}|${n.direction}`, n.backbone_position)
    }

    for (const pair of pairs) {
      const { helix_a_id, helix_b_id, positions } = pair
      for (const pos of positions) {
        // Skip scaffold positions and already-placed jumps.
        if (pos.is_scaffold_a || pos.is_scaffold_b) continue
        if (pos.half_ab_placed) continue

        const dirA = pos.direction_a
        const dirB = pos.direction_b

        const posA = nucMap.get(`${helix_a_id}|${pos.bp_a}|${dirA}`)
        const posB = nucMap.get(`${helix_b_id}|${pos.bp_b}|${dirB}`)
        if (!posA || !posB) continue

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
            helixAId:   helix_a_id,
            bpA:        pos.bp_a,
            directionA: dirA,
            helixBId:   helix_b_id,
            bpB:        pos.bp_b,
            directionB: dirB,
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

  function _isDeformBlocked() {
    return store.getState().deformToolActive
  }

  function _onMouseMove(e) {
    const rect = canvas.getBoundingClientRect()
    _mouse.x   = e.clientX - rect.left
    _mouse.y   = e.clientY - rect.top
    const state = store.getState()
    if (_markers.length && state.selectableTypes.crossovers && !_isDeformBlocked()) {
      _updateOpacities()
    } else {
      // Crossovers disabled or deform active — ensure nothing is highlighted and
      // all markers are faded to minimum opacity.
      if (_hoveredIdx >= 0 && _hoveredIdx < _markers.length) {
        _markers[_hoveredIdx].mesh.material.color.copy(COLOR_DEFAULT)
        _hoveredIdx = -1
      }
      const targetOpacity = _isDeformBlocked() ? 0 : OPACITY_MIN
      for (const m of _markers) {
        m.mesh.material.opacity = targetOpacity
        m.mesh.material.color.copy(COLOR_DEFAULT)
      }
    }
  }

  function _onPointerDown(e) {
    if (e.button !== 0 || _hoveredIdx < 0) return
    if (!store.getState().selectableTypes.crossovers) return
    if (_isDeformBlocked()) return  // deform tool has priority — never consume this event
    // Block OrbitControls from starting a drag when clicking a hovered marker.
    e.stopImmediatePropagation()
  }

  async function _onClick(e) {
    if (e.button !== 0 || _hoveredIdx < 0) return
    if (!store.getState().selectableTypes.crossovers) return
    if (_isDeformBlocked()) return  // deform tool active — ignore crossover clicks
    // Consume the event so blunt-end and strand selection handlers don't fire.
    e.stopImmediatePropagation()
    const { data } = _markers[_hoveredIdx]

    const result = await api.addHalfCrossover({
      helixAId:   data.helixAId,
      bpA:        data.bpA,
      directionA: data.directionA,
      helixBId:   data.helixBId,
      bpB:        data.bpB,
      directionB: data.directionB,
    })
    if (!result) {
      const err = store.getState().lastError
      console.error('Half-crossover placement failed:', err?.message)
    }
    // On success the store's currentGeometry changes → _refresh() is called
    // automatically by the subscription below.
  }

  canvas.addEventListener('mousemove', _onMouseMove)
  // Capture phase gives crossover interactions priority over OrbitControls and blunt-end rings.
  canvas.addEventListener('pointerdown', _onPointerDown, { capture: true })
  canvas.addEventListener('pointerup', _onClick, { capture: true })

  // Rebuild whenever the design or geometry changes (extrusion, crossover, undo, redo, etc.)
  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry !== prevState.currentGeometry ||
        newState.currentDesign   !== prevState.currentDesign) {
      _refresh()
    }
  })

  function dispose() {
    canvas.removeEventListener('mousemove', _onMouseMove)
    canvas.removeEventListener('pointerdown', _onPointerDown, { capture: true })
    canvas.removeEventListener('pointerup', _onClick, { capture: true })
    _clear()
    scene.remove(_group)
  }

  // isActive() always returns false — this system has no explicit active mode;
  // it is always on. The Escape handler in main.js checks this so it can fall
  // through to close the slice plane instead.
  return { dispose, clear: _clear, isActive: () => false }
}
