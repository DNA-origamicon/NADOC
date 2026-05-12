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
  // Axis line visibility state — 'deformed' | 'straight' | 'hidden'.
  // 'hidden' is set during an activate/deactivate lerp so the axis lines
  // don't sweep into position; the destination mode is set in the onDone
  // callback after the lerp completes.
  let _shaftMode = 'deformed'
  // True when a getStraightGeometry() fetch was skipped because cadnano was
  // active at the time.  Triggers a deferred fetch on cadnano exit.
  let _straightGeomStale = false

  // Map<"helix_id:bp_index:direction", THREE.Vector3> — straight nucleotide positions.
  let _straightPosMap  = new Map()
  // Map<"helix_id:bp_index:direction", THREE.Vector3> — straight base normals (cross-strand).
  let _straightBnMap   = new Map()
  // Map<helix_id, {start: THREE.Vector3, end: THREE.Vector3}> — straight axis anchors.
  let _straightAxesMap = new Map()

  // ── Topology comparison (fast invariant for straight-geometry cache) ────────
  //
  // Returns true if any topology field that affects straight nucleotide
  // positions changed between two designs. Linear pass over helices /
  // strand-domains / extensions / overhang_connections — much cheaper than
  // the alternative (a 5-second `apply_deformations=false` server round-trip).
  // Cluster transforms and deformations are intentionally ignored: they don't
  // move straight geometry (they're stripped on the backend's straight path).
  function _topologyChanged(prev, next) {
    if (!prev || !next) return true
    const pHel = prev.helices ?? []
    const nHel = next.helices ?? []
    if (pHel.length !== nHel.length) return true
    for (let i = 0; i < pHel.length; i++) {
      const p = pHel[i], n = nHel[i]
      if (p.id !== n.id || p.bp_start !== n.bp_start || p.length_bp !== n.length_bp) return true
      if (p.axis_start.x !== n.axis_start.x || p.axis_start.y !== n.axis_start.y || p.axis_start.z !== n.axis_start.z) return true
      if (p.axis_end.x !== n.axis_end.x || p.axis_end.y !== n.axis_end.y || p.axis_end.z !== n.axis_end.z) return true
    }
    const pStr = prev.strands ?? []
    const nStr = next.strands ?? []
    if (pStr.length !== nStr.length) return true
    for (let i = 0; i < pStr.length; i++) {
      const ps = pStr[i], ns = nStr[i]
      if (ps.id !== ns.id) return true
      const pd = ps.domains, nd = ns.domains
      if (pd.length !== nd.length) return true
      for (let j = 0; j < pd.length; j++) {
        const pdj = pd[j], ndj = nd[j]
        if (pdj.helix_id !== ndj.helix_id
            || pdj.start_bp !== ndj.start_bp
            || pdj.end_bp !== ndj.end_bp
            || pdj.direction !== ndj.direction) return true
      }
    }
    const pExt = prev.extensions ?? []
    const nExt = next.extensions ?? []
    if (pExt.length !== nExt.length) return true
    for (let i = 0; i < pExt.length; i++) {
      const p = pExt[i], n = nExt[i]
      if (p.id !== n.id || p.length !== n.length || p.end !== n.end || p.strand_id !== n.strand_id) return true
    }
    // ds-linker connections inject bridge nucs on synthetic __lnk__ helices.
    // Bridge bp count is derived from connection length, so any change in
    // count or length invalidates straight geometry too.
    const pCon = prev.overhang_connections ?? []
    const nCon = next.overhang_connections ?? []
    if (pCon.length !== nCon.length) return true
    for (let i = 0; i < pCon.length; i++) {
      const p = pCon[i], n = nCon[i]
      if (p.id !== n.id || p.linker_type !== n.linker_type
          || p.length_value !== n.length_value || p.length_unit !== n.length_unit) return true
    }
    return false
  }

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
        // Per-segment straight endpoints. Multi-segment curved helices
        // (e.g. compliant joints) use these so their per-segment axis
        // sticks lerp correctly between straight and deformed positions
        // without filling the gap between domains. Non-curved helices
        // also have segments, but the renderer keeps using the legacy
        // single-line lerp for them via _layStraightSegments.
        segments: ax.segments ?? null,
      })
    }
    return m
  }

  function _applyLerp(t) {
    // Re-assert the current shaft mode every frame so it stays correct
    // across scene rebuilds (new axisArrows start with default visibility)
    // and across physics/deform-tool transitions. _shaftMode is owned by
    // activate/deactivate/snapOff/setT — during a lerp it's 'hidden',
    // at rest it's 'deformed' or 'straight'.
    designRenderer.setAxisShaftMode(_shaftMode)
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
    // Hide ALL axis lines for the duration of the lerp; the curved deformed
    // shaft only appears at the end (onDone). Mid-lerp visibility would
    // sweep into position, which the user does not want.
    _active = true
    _shaftMode = 'hidden'
    designRenderer.setAxisShaftMode('hidden')
    if (_straightPosMap.size === 0) await getStraightGeometry()
    store.setState({ deformVisuActive: true })
    _animate(_currentT, 1, () => {
      _shaftMode = 'deformed'
      designRenderer.setAxisShaftMode('deformed')
    })
  }

  function deactivate() {
    // Mirror of activate: axes hidden during the lerp, straight axis
    // appears at the end.
    _active = false
    _shaftMode = 'hidden'
    designRenderer.setAxisShaftMode('hidden')
    _animate(_currentT, 0, () => {
      _currentT = 0
      _shaftMode = 'straight'
      designRenderer.setAxisShaftMode('straight')
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
    _shaftMode = 'straight'
    designRenderer.setAxisShaftMode('straight')
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
    } else if (newState.straightGeometry !== prevState.straightGeometry
               && newState.straightGeometry) {
      // The current setState batch ALSO updated straightGeometry (the backend
      // embedded `straight_positions_by_helix` + `straight_helix_axes` in
      // the response — see _design_response_with_geometry's auto-embed).
      // The straight maps will be rebuilt by the dedicated straightGeometry
      // subscriber below; nothing to fetch here. This is the expected path
      // for every topology-changing mutation when deformations exist.
    } else if (newState.straightGeometry
               && !_topologyChanged(prevState.currentDesign, newState.currentDesign)) {
      // Straight geometry depends only on topology. When topology is
      // unchanged — e.g. slider seek across deformation-edit entries — the
      // existing straightGeometry is still valid and no refetch is needed.
    } else {
      // Safety net. With Move A in place (auto-embed on the backend), this
      // branch should not fire: any topology-changing response that has
      // deformations or cluster_transforms will embed straight geometry, and
      // any response without those falls through the hasDeformations/
      // hasTransforms fast path above. If we hit this, the backend missed
      // a path — log loudly so it can be tracked down — but still fetch so
      // the user sees a correct view.
      console.warn('[deform_view] straight geometry not embedded in response and topology changed; ' +
                   'falling back to explicit getStraightGeometry() fetch. ' +
                   'This indicates a backend response that should have auto-embedded but did not.')
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
      _shaftMode = 'straight'
      _applyLerp(0)  // snap positions to straight immediately
    }
  })

  // Auto-reactivate deformed view when the design transitions to a state
  // with no deformations AND no non-identity cluster transforms. In that
  // state the deformed/straight toggle has no visual effect (straight ==
  // current), so the user-facing default ON is the correct resting state.
  // Fires after delete-feature-log-entry, undo/redo, or any other path that
  // removes the last deformation/transform.
  //
  // Skipped while cadnano or unfold is active — both modes require deform
  // OFF as a precondition and own their own bead positions. activate() while
  // they're active would fight for control of the lerp.
  function _hasEffectiveTransform(design) {
    return !!(design?.cluster_transforms?.some(ct => {
      const [x, y, z, w] = ct.rotation
      const [tx, ty, tz] = ct.translation
      return Math.abs(x) > 1e-9 || Math.abs(y) > 1e-9 || Math.abs(z) > 1e-9 || Math.abs(w - 1) > 1e-9
          || Math.abs(tx) > 1e-9 || Math.abs(ty) > 1e-9 || Math.abs(tz) > 1e-9
    }))
  }
  store.subscribe(async (newState, prevState) => {
    if (newState.currentDesign === prevState.currentDesign) return
    if (_active) return  // already on — nothing to do
    if (newState.cadnanoActive || newState.unfoldActive) return
    const prevHadDef = (prevState.currentDesign?.deformations?.length ?? 0) > 0
    const prevHadXf  = _hasEffectiveTransform(prevState.currentDesign)
    const nowHasDef  = (newState.currentDesign?.deformations?.length ?? 0) > 0
    const nowHasXf   = _hasEffectiveTransform(newState.currentDesign)
    // Reactivate iff we had something to suppress before AND there's nothing
    // to suppress now. Avoids snapping the toggle on for unrelated design
    // mutations while deform-off is the user's intentional state.
    if ((prevHadDef || prevHadXf) && !nowHasDef && !nowHasXf) {
      await activate()
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
    // Axis lines: visible only at endpoints (t === 0 → straight, t === 1
    // → deformed). Intermediate values are mid-animation in the player's
    // view; hide axes so they don't sweep into position. Same rule as the
    // user-facing toggle.
    _active = _currentT > 0
    _shaftMode = _currentT === 0 ? 'straight'
              : _currentT === 1 ? 'deformed'
              : 'hidden'
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
