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

  // ── Geometric scene rebuild ───────────────────────────────────────────────

  function _rebuild(geometry, design, helixAxes) {
    // Dispose previous scene objects.
    if (_helixCtrl?.root) {
      scene.remove(_helixCtrl.root)
      _helixCtrl.root.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose()
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose())
          else obj.material.dispose()
        }
      })
    }

    if (!geometry || !design || geometry.length === 0) {
      _helixCtrl = null
      return
    }

    const { strandColors, loopStrandIds } = storeRef.getState()
    _helixCtrl = buildHelixObjects(geometry, design, scene, strandColors, loopStrandIds ?? [], helixAxes)
    _helixCtrl.setMode(_currentMode)
  }

  // Subscribe to store changes and rebuild when geometry or design changes.
  storeRef.subscribe((newState, prevState) => {
    if (
      newState.currentGeometry  !== prevState.currentGeometry  ||
      newState.currentDesign    !== prevState.currentDesign    ||
      newState.loopStrandIds    !== prevState.loopStrandIds    ||
      newState.currentHelixAxes !== prevState.currentHelixAxes
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

    // ── Instance update delegates (used by selection_manager) ─────────────
    setEntryColor(entry, hex)  { _helixCtrl?.setEntryColor(entry, hex) },
    setBeadScale(entry, s)     { _helixCtrl?.setBeadScale(entry, s) },
    setConeXZScale(entry, r)   { _helixCtrl?.setConeXZScale(entry, r) },

    /**
     * Apply a custom colour to a strand and persist it in the store so it
     * survives scene rebuilds.
     */
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
     * Apply per-helix translation offsets for the 2D unfold animation.
     * Delegates to helixCtrl; returns cross-helix connections for arc drawing.
     *
     * @param {Map<string, THREE.Vector3>} helixOffsets
     * @param {number} t  lerp factor 0→1
     * @returns {Array<{from, to}>|[]}
     */
    applyUnfoldOffsets(helixOffsets, t) {
      return _helixCtrl?.applyUnfoldOffsets(helixOffsets, t) ?? []
    },

    /**
     * Return cross-helix backbone connections at current world positions.
     * Called by unfold_view.js when geometry is loaded/changed.
     */
    getCrossHelixConnections() {
      return _helixCtrl?.getCrossHelixConnections() ?? []
    },

    getDistLabelInfo() {
      return _helixCtrl?.getDistLabelInfo() ?? null
    },

    /**
     * Fade all geometry to `opacity` (0–1).  Used by the deformation editor
     * to dim the scene when the bend/twist tool is active.
     */
    setToolOpacity(opacity) {
      if (!_helixCtrl?.root) return
      _helixCtrl.root.traverse(obj => {
        if (!obj.material) return
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        for (const m of mats) {
          m.transparent = opacity < 1.0
          m.opacity = opacity
        }
      })
    },

    dispose() {
      if (_helixCtrl?.root) scene.remove(_helixCtrl.root)
      _helixCtrl = null
    },
  }
}
