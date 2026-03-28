/**
 * Design renderer — reactive Three.js scene builder.
 *
 * Wraps the helix renderer logic and rebuilds the scene whenever the store's
 * currentDesign or currentGeometry changes.  Exposes getBackboneEntries() for
 * the selection manager to raycast against.
 *
 * Physics mode (Phase 5):
 *   When store.physicsPositions is non-null, the actual backbone beads, cones,
 *   and slabs are moved to the XPBD-relaxed positions in-place via
 *   helixCtrl.applyPhysicsPositions().  Toggling off calls revertToGeometry()
 *   which snaps everything back to designed (B-DNA ideal) positions exactly
 *   (V5.3 toggle requirement).
 *
 * Usage:
 *   const dr = initDesignRenderer(scene, store)
 *   dr.setMode('V1.2')
 *   dr.getBackboneEntries()  // → [{ mesh, nuc }, ...]
 */

import { buildHelixObjects } from './helix_renderer.js'
import { createGlowLayer }  from './glow_layer.js'

/**
 * Initialise the design renderer.
 *
 * @param {THREE.Scene} scene
 * @param {import('../state/store.js').store} storeRef
 * @returns {{ setMode, getBackboneEntries, setStrandColor, getHelixCtrl,
 *             applyPhysicsPositions, dispose }}
 */
export function initDesignRenderer(scene, storeRef) {
  let _helixCtrl   = null
  let _currentMode = 'normal'
  const _glowLayer = createGlowLayer(scene)

  // ── Preview ghost state ───────────────────────────────────────────────────
  // When a bend/twist preview is active:
  //   _ghostRoot  — the original (pre-bend) geometry group kept in the scene
  //   _previewOpacity — opacity applied to each newly rebuilt preview geometry
  // Both are null when not in preview mode.

  let _ghostRoot       = null   // saved pre-preview root (not disposed)
  let _previewOpacity  = null   // opacity for the bent preview geometry
  // Flag: on the NEXT _rebuild, save the old root as ghost instead of disposing
  let _captureNextAsGhost    = null   // ghost opacity value, or null
  let _captureNextPreviewOp  = null   // preview opacity value

  function _disposeRoot(root) {
    root.traverse(obj => {
      if (obj.geometry) obj.geometry.dispose()
      if (obj.material) {
        if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose())
        else obj.material.dispose()
      }
    })
  }

  function _traverseSetOpacity(root, opacity) {
    root.traverse(obj => {
      if (!obj.material) return
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
      for (const m of mats) { m.transparent = opacity < 1.0; m.opacity = opacity }
    })
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  /** Merge strandColors (hex numbers) with group color overrides (hex strings). */
  function _effectiveColors(strandColors, strandGroups) {
    const result = { ...strandColors }
    for (const group of strandGroups ?? []) {
      if (group.color) {
        const hex = parseInt(group.color.replace('#', ''), 16)
        for (const sid of group.strandIds) result[sid] = hex
      }
    }
    return result
  }

  // ── Geometric scene rebuild ───────────────────────────────────────────────

  function _rebuild(geometry, design, helixAxes) {
    // Dispose or save previous scene objects.
    if (_helixCtrl?.root) {
      const oldRoot = _helixCtrl.root
      scene.remove(oldRoot)

      if (_captureNextAsGhost !== null) {
        // Save old geometry as ghost — do NOT dispose
        if (_ghostRoot) { _disposeRoot(_ghostRoot); scene.remove(_ghostRoot) }
        _ghostRoot = oldRoot
        _traverseSetOpacity(_ghostRoot, _captureNextAsGhost)
        scene.add(_ghostRoot)
        _previewOpacity = _captureNextPreviewOp
        _captureNextAsGhost   = null
        _captureNextPreviewOp = null
      } else if (oldRoot !== _ghostRoot) {
        // Normal disposal (ghost is managed separately)
        _disposeRoot(oldRoot)
      }
    }

    _glowLayer.clear()   // stale entries after rebuild; selection_manager re-applies if needed

    if (!geometry || !design || geometry.length === 0) {
      _helixCtrl = null
      return
    }

    const { strandColors, strandGroups, loopStrandIds, staplesHidden, isolatedStrandId } = storeRef.getState()
    _helixCtrl = buildHelixObjects(geometry, design, scene, _effectiveColors(strandColors, strandGroups), loopStrandIds ?? [], helixAxes)
    _helixCtrl.setMode(_currentMode)

    // Re-apply post-rebuild visibility state
    if (staplesHidden) _helixCtrl.setStapleVisibility(false)
    if (isolatedStrandId) _helixCtrl.setIsolatedStrand(isolatedStrandId)

    // Apply opacity for preview or tool-dim modes
    if (_previewOpacity !== null) {
      _traverseSetOpacity(_helixCtrl.root, _previewOpacity)
    } else if (storeRef.getState().deformToolActive) {
      _traverseSetOpacity(_helixCtrl.root, 0.15)
    }
  }

  // Subscribe to store changes and rebuild when geometry or design changes.
  storeRef.subscribe((newState, prevState) => {
    if (
      newState.currentGeometry  !== prevState.currentGeometry  ||
      newState.currentDesign    !== prevState.currentDesign    ||
      newState.loopStrandIds    !== prevState.loopStrandIds    ||
      newState.currentHelixAxes !== prevState.currentHelixAxes ||
      newState.strandGroups     !== prevState.strandGroups
    ) {
      _rebuild(newState.currentGeometry, newState.currentDesign, newState.currentHelixAxes)
    }

    // React to physicsPositions changes: move actual beads/cones/slabs.
    if (newState.physicsPositions !== prevState.physicsPositions) {
      if (!newState.physicsPositions) {
        _helixCtrl?.revertToGeometry()
      } else {
        _helixCtrl?.applyPhysicsPositions(newState.physicsPositions)
      }
    }

    // Thicken axis arrows when the bend/twist deformation tool is active.
    if (newState.deformToolActive !== prevState.deformToolActive) {
      _helixCtrl?.setDeformMode(!!newState.deformToolActive)
    }

    // Hide/show all staple strands.
    if (newState.staplesHidden !== prevState.staplesHidden) {
      _helixCtrl?.setStapleVisibility(!newState.staplesHidden)
    }

    // Isolate a single staple strand (dim all others).
    if (newState.isolatedStrandId !== prevState.isolatedStrandId) {
      _helixCtrl?.setIsolatedStrand(newState.isolatedStrandId)
    }
  })

  // Build immediately if the store already has data (e.g. on hot reload).
  const { currentGeometry, currentDesign, currentHelixAxes } = storeRef.getState()
  if (currentGeometry && currentDesign) {
    _rebuild(currentGeometry, currentDesign, currentHelixAxes)
  }

  return {
    setMode(mode) {
      _currentMode = mode
      _helixCtrl?.setMode(mode)
    },

    getBackboneEntries() {
      return _helixCtrl?.backboneEntries ?? []
    },

    getConeEntries() {
      return _helixCtrl?.coneEntries ?? []
    },

    getSlabEntries() {
      return _helixCtrl?.slabEntries ?? []
    },

    // ── Instance update delegates (used by selection_manager) ─────────────
    setEntryColor(entry, hex)  { _helixCtrl?.setEntryColor(entry, hex) },
    setBeadScale(entry, s)     { _helixCtrl?.setBeadScale(entry, s) },
    setConeXZScale(entry, r)   { _helixCtrl?.setConeXZScale(entry, r) },

    /**
     * Apply a custom colour to a strand and persist it in the store so it
     * survives scene rebuilds.
     */
    /** Show green additive-blend glow spheres over the given backbone entries. */
    setGlowEntries(entries) { _glowLayer.setEntries(entries) },
    clearGlow()              { _glowLayer.clear() },

    setStrandColor(strandId, hexColor) {
      const { strandColors } = storeRef.getState()
      storeRef.setState({ strandColors: { ...strandColors, [strandId]: hexColor } })
      _helixCtrl?.setStrandColor(strandId, hexColor)
    },

    /**
     * Drive physics from WebSocket position updates.
     * Moves the actual scene objects; null reverts everything to geometry.
     *
     * @param {Array<{helix_id, bp_index, direction, backbone_position}>|null} updates
     */
    applyPhysicsPositions(updates) {
      if (!updates) {
        _helixCtrl?.revertToGeometry()
        storeRef.setState({ physicsPositions: null })
      } else {
        storeRef.setState({ physicsPositions: updates })
      }
    },

    getHelixCtrl() {
      return _helixCtrl
    },

    /**
     * Apply FEM equilibrium-shape positions as a scene overlay.
     * @param {Array<{helix_id, bp_index, direction, backbone_position}>} updates
     */
    applyFemPositions(updates) {
      _helixCtrl?.applyFemPositions(updates)
    },

    /**
     * Colour beads and slabs by RMSF value (stiff=blue, flexible=red).
     * @param {Object} rmsfMap  "{helix_id}:{bp}:{dir}" → float 0-1
     */
    applyFemRmsf(rmsfMap) {
      _helixCtrl?.applyFemRmsf(rmsfMap)
    },

    /**
     * Remove FEM overlay: revert geometry positions and restore strand colours.
     */
    clearFemOverlay() {
      _helixCtrl?.revertToGeometry()
      _helixCtrl?.clearFemColors()
    },

    /**
     * Apply per-helix translation offsets for the 2D unfold animation.
     * Delegates to helixCtrl; returns cross-helix connections for arc drawing.
     *
     * @param {Map<string, THREE.Vector3>} helixOffsets
     * @param {number} t  lerp factor 0→1
     * @returns {Array<{from, to}>|[]}
     */
    applyUnfoldOffsets(helixOffsets, t, straightPosMap, straightAxesMap) {
      return _helixCtrl?.applyUnfoldOffsets(helixOffsets, t, straightPosMap, straightAxesMap) ?? []
    },

    applyUnfoldOffsetsExtraBases(xbArcMap, t) {
      _helixCtrl?.applyUnfoldOffsetsExtraBases(xbArcMap, t)
    },

    /**
     * Lerp all geometry between straight and deformed positions.
     * @param {Map<string, THREE.Vector3>} straightPosMap  key "hid:bp:dir" → straight pos
     * @param {Map<string, {start,end}>} straightAxesMap   key helix_id → straight axis anchors
     * @param {number} t  lerp factor 0=straight, 1=deformed
     */
    applyDeformLerp(straightPosMap, straightAxesMap, t) {
      _helixCtrl?.applyDeformLerp(straightPosMap, straightAxesMap, t)
    },

    /**
     * Return cross-helix backbone connections at current world positions.
     * Called by unfold_view.js when geometry is loaded/changed.
     */
    getCrossHelixConnections() {
      return _helixCtrl?.getCrossHelixConnections() ?? []
    },

    getAxisArrows() {
      return _helixCtrl?.getAxisArrows() ?? []
    },

    getDistLabelInfo() {
      return _helixCtrl?.getDistLabelInfo() ?? null
    },

    /**
     * Fade all geometry to `opacity` (0–1).  Used by the deformation editor
     * to dim the scene when the bend/twist tool is active.
     * Skipped when preview ghost mode is active (opacity managed by _previewOpacity).
     */
    setToolOpacity(opacity) {
      if (_previewOpacity !== null) return   // preview mode manages its own opacity
      if (!_helixCtrl?.root) return
      _traverseSetOpacity(_helixCtrl.root, opacity)
    },

    /**
     * Save the current geometry as a ghost overlay at `ghostOpacity`, and mark
     * that the next rebuilt geometry (the bent preview) should appear at
     * `previewOpacity`.  Call before triggering the API deformation.
     */
    captureGhost(ghostOpacity, previewOpacity) {
      if (!_helixCtrl?.root) return
      _captureNextAsGhost   = ghostOpacity
      _captureNextPreviewOp = previewOpacity
    },

    /**
     * Remove the ghost overlay and exit preview opacity mode.
     * The next rebuild will use the normal tool dim (0.15) if the tool is active.
     */
    clearGhost() {
      if (_ghostRoot) { _disposeRoot(_ghostRoot); scene.remove(_ghostRoot); _ghostRoot = null }
      _previewOpacity       = null
      _captureNextAsGhost   = null
      _captureNextPreviewOp = null
    },

    dispose() {
      if (_ghostRoot) { scene.remove(_ghostRoot); _ghostRoot = null }
      if (_helixCtrl?.root) scene.remove(_helixCtrl.root)
      _helixCtrl = null
    },
  }
}
