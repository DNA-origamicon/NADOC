/**
 * Deformed Geometry View — lerps helices between straight (t=0) and deformed (t=1).
 *
 *   t = 0  → straight bundle geometry (deformations ignored)
 *   t = 1  → deformed positions from the active DeformationOps
 *
 * The view starts ACTIVE (t=1) by default and cannot be deactivated unless the
 * design has at least one DeformationOp.  With no deformations straight=deformed
 * so t=0/t=1 are visually identical.
 *
 * Usage:
 *   const deformView = initDeformView(designRenderer, getBluntEnds)
 *   deformView.activate()    // animate t → 1
 *   deformView.deactivate()  // animate t → 0 (straight)
 *   deformView.isActive()    // → boolean
 *   deformView.dispose()
 */

import * as THREE from 'three'
import { store } from '../state/store.js'
import { getStraightGeometry } from '../api/client.js'

const ANIM_DURATION_MS = 500

export function initDeformView(designRenderer, getBluntEnds, _getCrossoverMarkers, getUnfoldView, getLoopSkipHighlight, getOverhangLocations, getJointRenderer) {
  // Starts active at t=1 — matches store default deformVisuActive: true.
  let _active    = true
  let _animFrame = null
  let _currentT  = 1
  // True when a getStraightGeometry() fetch was skipped because cadnano was
  // active at the time.  Triggers a deferred fetch on cadnano exit.
  let _straightGeomStale = false

  // Map<"helix_id:bp_index:direction", THREE.Vector3> — straight nucleotide positions.
  let _straightPosMap  = new Map()
  // Map<"helix_id:bp_index:direction", THREE.Vector3> — straight base normals (cross-strand).
  let _straightBnMap   = new Map()
  // Map<helix_id, {start: THREE.Vector3, end: THREE.Vector3}> — straight axis anchors.
  let _straightAxesMap = new Map()

  // ── Map builders ────────────────────────────────────────────────────────────

  function _buildStraightPosMap(straightGeometry) {
    const m = new Map()
    if (!straightGeometry) return m
    for (const nuc of straightGeometry) {
      const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
      const bp  = nuc.backbone_position
      m.set(key, new THREE.Vector3(bp[0], bp[1], bp[2]))
    }
    return m
  }

  function _buildStraightBnMap(straightGeometry) {
    const m = new Map()
    if (!straightGeometry) return m
    for (const nuc of straightGeometry) {
      const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
      const bn  = nuc.base_normal
      m.set(key, new THREE.Vector3(bn[0], bn[1], bn[2]))
    }
    return m
  }

  function _buildStraightAxesMap(straightHelixAxes) {
    const m = new Map()
    if (!straightHelixAxes) return m
    for (const [helixId, ax] of Object.entries(straightHelixAxes)) {
      m.set(helixId, {
        start: new THREE.Vector3(...ax.start),
        end:   new THREE.Vector3(...ax.end),
      })
    }
    return m
  }

  function _applyLerp(t) {
    designRenderer.applyDeformLerp(_straightPosMap, _straightAxesMap, _straightBnMap, t)
    getBluntEnds?.()?.applyDeformLerp(_straightAxesMap, t)
    getUnfoldView?.()?.applyDeformLerp(_straightPosMap, t)
    getLoopSkipHighlight?.()?.applyDeformLerp(_straightPosMap, _straightAxesMap, t)
    getOverhangLocations?.()?.applyDeformLerp(_straightPosMap, _straightAxesMap, t)
    getJointRenderer?.()?.applyDeformLerp(t)
  }

  // ── Animation ───────────────────────────────────────────────────────────────

  function _animate(fromT, toT, onDone) {
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
    const startTime = performance.now()

    function frame(now) {
      const raw = Math.min((now - startTime) / ANIM_DURATION_MS, 1)
      const t   = fromT + (toT - fromT) * raw

      _applyLerp(t)
      _currentT = t

      if (raw >= 1) {
        _animFrame = null
        onDone?.()
      } else {
        _animFrame = requestAnimationFrame(frame)
      }
    }

    _animFrame = requestAnimationFrame(frame)
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  async function activate() {
    if (_straightPosMap.size === 0) await getStraightGeometry()
    _active = true
    store.setState({ deformVisuActive: true })
    _animate(_currentT, 1, null)
  }

  function deactivate() {
    _animate(_currentT, 0, () => {
      _active   = false
      _currentT = 0
      store.setState({ deformVisuActive: false })
      // Scene stays at straight positions (t=0) — that is the intended OFF state.
    })
  }

  /** Immediately snap to straight (t=0) without animation.  Used when another
   *  view (unfold) needs positions to be straight before its own animation starts. */
  function snapOff() {
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
    _active   = false
    _currentT = 0
    _applyLerp(0)
    store.setState({ deformVisuActive: false })
  }

  // ── Store subscriptions ──────────────────────────────────────────────────────

  // Rebuild maps whenever straight geometry changes.
  store.subscribe((newState, prevState) => {
    const geoChanged  = newState.straightGeometry  !== prevState.straightGeometry
    const axesChanged = newState.straightHelixAxes !== prevState.straightHelixAxes
    if (!geoChanged && !axesChanged) return

    if (geoChanged)  {
      _straightPosMap = _buildStraightPosMap(newState.straightGeometry)
      _straightBnMap  = _buildStraightBnMap(newState.straightGeometry)
    }
    if (axesChanged) _straightAxesMap = _buildStraightAxesMap(newState.straightHelixAxes)

    // Re-apply lerp at the current t so the view stays in sync.
    // Skip when cadnano is active — cadnano_view manages bead positions there;
    // a compensating reapplyPositions() subscriber in main.js handles this case.
    if (!store.getState().cadnanoActive) _applyLerp(_currentT)
  })

  // When currentGeometry changes (undo/redo, topology mutation, new deformation):
  // update straight geometry and restore the correct deform-view state.
  store.subscribe(async (newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry) return

    const hasDeformations = (newState.currentDesign?.deformations?.length       ?? 0) > 0
    const hasTransforms   = (newState.currentDesign?.cluster_transforms?.length ?? 0) > 0

    if (!hasDeformations && !hasTransforms) {
      // Nothing shifts positions — straight geometry equals current geometry.
      // Build maps directly to avoid a redundant round-trip.
      _straightPosMap  = _buildStraightPosMap(newState.currentGeometry)
      _straightBnMap   = _buildStraightBnMap(newState.currentGeometry)
      _straightAxesMap = _buildStraightAxesMap(newState.currentHelixAxes)
    } else if (store.getState().cadnanoActive) {
      // Cadnano is active: the fetch is not needed right now (cadnano positions
      // override whatever deformView would place).  Defer until cadnano exits.
      _currentT = _active ? 1 : 0
      _straightGeomStale = true
      return
    } else {
      // Deformations or cluster transforms are applied — straight ≠ current.
      // Fetch the pure topology positions (no deformations, no transforms).
      await getStraightGeometry()
    }

    // Update _currentT unconditionally so state is correct after cadnano exits.
    _currentT = _active ? 1 : 0

    if (store.getState().cadnanoActive) {
      // cadnanoActive became true while getStraightGeometry() was in-flight
      // (extremely unlikely, but guard anyway).
      return
    }

    _applyLerp(_currentT)
    // If the unfold view is active, _applyLerp above will have reset helix positions
    // to straight 3D (because it ran asynchronously after the unfold subscription
    // already applied offsets).  Reapply unfold so the user stays in 2D view.
    getUnfoldView?.()?.reapplyIfActive()
  })

  // Handle deformVisuActive being cleared externally (e.g. when unfold is toggled on).
  store.subscribe((newState, prevState) => {
    if (newState.deformVisuActive === prevState.deformVisuActive) return
    if (!newState.deformVisuActive && _active) {
      if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
      _active   = false
      _currentT = 0
      _applyLerp(0)  // snap positions to straight immediately
    }
  })

  // When cadnano exits, fetch the straight geometry that was deferred during the session.
  // The fetch completes → straightGeometry subscriber above fires → _applyLerp(_currentT).
  store.subscribe(async (newState, prevState) => {
    if (newState.cadnanoActive === prevState.cadnanoActive) return
    if (!newState.cadnanoActive && _straightGeomStale) {
      _straightGeomStale = false
      await getStraightGeometry()
    }
  })

  // When the deform tool exits, design_renderer calls _traverseSetOpacity(1.0) which
  // resets ALL material opacities — including the shaft/straightShaft cross-fade managed
  // by the deform lerp.  Re-apply the lerp to restore the correct shaft visibility.
  store.subscribe((newState, prevState) => {
    if (newState.deformToolActive === prevState.deformToolActive) return
    if (!newState.deformToolActive) _applyLerp(_currentT)
  })

  /** Re-apply the lerp at the current t without animating.
   *  Call this after physics is stopped so the view snaps back to the
   *  correct deform state (straight when t=0, deformed when t=1). */
  function reapplyLerp() {
    _applyLerp(_currentT)
  }

  /**
   * Directly set the deform interpolation value without animating.
   * Cancels any in-progress animation.  Used by the animation player
   * to drive the deform state frame-by-frame.
   * @param {number} t — value in [0, 1]
   */
  function setT(t) {
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
    _currentT = Math.max(0, Math.min(1, t))
    _applyLerp(_currentT)
  }

  /** Returns the current deform interpolation value. */
  function getT() { return _currentT }

  return {
    activate,
    deactivate,
    snapOff,
    reapplyLerp,
    setT,
    getT,
    isActive: () => _active,
    dispose() {
      if (_animFrame) cancelAnimationFrame(_animFrame)
    },
  }
}
