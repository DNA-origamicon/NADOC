/**
 * 2D Unfold View — animates helices from their 3D lattice positions to a
 * linear horizontal stack (caDNAno-style Path Panel).
 *
 * Each helix is translated so its axis midpoint sits at (0, −i × spacing, z),
 * stacked top-to-bottom in the order stored in store.unfoldHelixOrder.
 * Cross-helix strand connections (placed crossovers) are hidden as cones and
 * replaced with QuadraticBezierCurve3 arcs bowing outward in Z.
 *
 * Usage:
 *   const unfoldView = initUnfoldView(scene, designRenderer, store)
 *   unfoldView.toggle()           // activate / deactivate
 *   unfoldView.setSpacing(3.0)    // change row spacing in nm
 *   unfoldView.isActive()         // → boolean
 *   unfoldView.dispose()
 */

import * as THREE from 'three'
import { store } from '../state/store.js'

const ANIM_DURATION_MS = 500   // linear lerp duration
const ARC_TUBE_RADIUS  = 0.025 // nm — arc tube cross-section

export function initUnfoldView(scene, designRenderer, getBluntEnds) {
  let _active     = false
  let _animFrame  = null
  let _currentT   = 0

  const _arcGroup = new THREE.Group()
  scene.add(_arcGroup)

  // ── Offset computation ──────────────────────────────────────────────────────

  /**
   * Build a Map<helix_id, THREE.Vector3> where each Vector3 is the translation
   * that moves the helix midpoint to its unfolded row position.
   */
  function _buildOffsets(spacing) {
    const { currentDesign, unfoldHelixOrder } = store.getState()
    if (!currentDesign) return new Map()

    // Fall back to design order if no explicit selection order is stored.
    const order = unfoldHelixOrder
      ?? currentDesign.helices.map(h => h.id)

    const helixMap = new Map(currentDesign.helices.map(h => [h.id, h]))
    const offsets  = new Map()

    let row = 0
    for (const helixId of order) {
      const h = helixMap.get(helixId)
      if (!h) continue

      const cx = (h.axis_start.x + h.axis_end.x) / 2
      const cy = (h.axis_start.y + h.axis_end.y) / 2

      offsets.set(helixId, new THREE.Vector3(
        -cx,                   // centre at x = 0
        -row * spacing - cy,   // stack downward
        0,                     // keep z unchanged
      ))
      row++
    }
    return offsets
  }

  // ── Arc overlay ─────────────────────────────────────────────────────────────

  function _clearArcs() {
    for (const child of [..._arcGroup.children]) {
      _arcGroup.remove(child)
      child.geometry?.dispose()
      child.material?.dispose()
    }
  }

  /**
   * Draw QuadraticBezierCurve3 tube arcs for each cross-helix strand connection.
   * The control point bows in +Z proportional to the distance between endpoints,
   * giving a visual separation analogous to caDNAno's crossover arcs.
   */
  function _buildArcs(crossHelixConns) {
    _clearArcs()
    for (const { from, to } of crossHelixConns) {
      const mid = from.clone().lerp(to, 0.5)
      const dist = from.distanceTo(to)
      mid.z += dist * 0.5   // bow toward camera

      const curve  = new THREE.QuadraticBezierCurve3(from, mid, to)
      const geo    = new THREE.TubeGeometry(curve, 20, ARC_TUBE_RADIUS, 6, false)
      const mat    = new THREE.MeshBasicMaterial({
        color:       0x00ccff,
        opacity:     0.75,
        transparent: true,
      })
      _arcGroup.add(new THREE.Mesh(geo, mat))
    }
  }

  // ── Animation ───────────────────────────────────────────────────────────────

  function _animate(fromT, toT, offsets, onDone) {
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
    const startTime = performance.now()

    function frame(now) {
      const raw = Math.min((now - startTime) / ANIM_DURATION_MS, 1)
      const t   = fromT + (toT - fromT) * raw   // linear lerp

      const conns = designRenderer.applyUnfoldOffsets(offsets, t)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, t)
      _currentT = t

      if (raw >= 1) {
        _animFrame = null
        onDone?.(conns)
      } else {
        _animFrame = requestAnimationFrame(frame)
      }
    }

    _animFrame = requestAnimationFrame(frame)
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  function activate() {
    const spacing = store.getState().unfoldSpacing
    const offsets = _buildOffsets(spacing)
    _active = true
    store.setState({ unfoldActive: true })
    _animate(_currentT, 1, offsets, conns => _buildArcs(conns))
  }

  function deactivate() {
    const spacing = store.getState().unfoldSpacing
    const offsets = _buildOffsets(spacing)
    _clearArcs()
    _animate(_currentT, 0, offsets, () => {
      _active = false
      store.setState({ unfoldActive: false })
      designRenderer.getHelixCtrl()?.revertToGeometry()
    })
  }

  function toggle() {
    if (_active) deactivate()
    else activate()
  }

  function setSpacing(nm) {
    store.setState({ unfoldSpacing: nm })
    if (_active) {
      // Re-apply immediately at t=1.
      const offsets = _buildOffsets(nm)
      const conns   = designRenderer.applyUnfoldOffsets(offsets, 1)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, 1)
      _buildArcs(conns)
    }
  }

  // Deactivate unfold when a new design is loaded (topology changes invalidate offsets).
  store.subscribe((newState, prevState) => {
    if (newState.currentDesign !== prevState.currentDesign && _active) {
      if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
      _clearArcs()
      _active   = false
      _currentT = 0
      store.setState({ unfoldActive: false })
    }
  })

  return {
    toggle,
    activate,
    deactivate,
    setSpacing,
    isActive: () => _active,
    dispose() {
      if (_animFrame) cancelAnimationFrame(_animFrame)
      _clearArcs()
      scene.remove(_arcGroup)
    },
  }
}
