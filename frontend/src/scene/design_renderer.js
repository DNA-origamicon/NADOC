/**
 * Design renderer — reactive Three.js scene builder.
 *
 * Wraps the helix renderer logic and rebuilds the scene whenever the store's
 * currentDesign or currentGeometry changes.  Exposes getBackboneEntries() for
 * the selection manager to raycast against.
 *
 * Usage:
 *   const dr = initDesignRenderer(scene, store)
 *   dr.setMode('V1.2')
 *   dr.getBackboneEntries()  // → [{ mesh, nuc }, ...]
 */

import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'

/**
 * Initialise the design renderer.
 *
 * @param {THREE.Scene} scene
 * @param {import('../state/store.js').store} storeRef
 * @returns {{ setMode, getBackboneEntries, setStrandColor, getHelixCtrl, dispose }}
 */
export function initDesignRenderer(scene, storeRef) {
  let _helixCtrl = null
  let _currentMode = 'normal'

  function _rebuild(geometry, design) {
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

    const { strandColors } = storeRef.getState()
    _helixCtrl = buildHelixObjects(geometry, design, scene, strandColors)
    _helixCtrl.setMode(_currentMode)
  }

  // Subscribe to store changes and rebuild when geometry or design changes.
  storeRef.subscribe((newState, prevState) => {
    if (
      newState.currentGeometry !== prevState.currentGeometry ||
      newState.currentDesign  !== prevState.currentDesign
    ) {
      _rebuild(newState.currentGeometry, newState.currentDesign)
    }
  })

  // Build immediately if the store already has data (e.g. on hot reload).
  const { currentGeometry, currentDesign } = storeRef.getState()
  if (currentGeometry && currentDesign) {
    _rebuild(currentGeometry, currentDesign)
  }

  return {
    setMode(mode) {
      _currentMode = mode
      _helixCtrl?.setMode(mode)
    },

    getBackboneEntries() {
      return _helixCtrl?.backboneEntries ?? []
    },

    /**
     * Apply a custom colour to a strand and persist it in the store so it
     * survives scene rebuilds.
     */
    setStrandColor(strandId, hexColor) {
      const { strandColors } = storeRef.getState()
      storeRef.setState({ strandColors: { ...strandColors, [strandId]: hexColor } })
      _helixCtrl?.setStrandColor(strandId, hexColor)
    },

    getHelixCtrl() {
      return _helixCtrl
    },

    getDistLabelInfo() {
      return _helixCtrl?.getDistLabelInfo() ?? null
    },

    dispose() {
      if (_helixCtrl?.root) scene.remove(_helixCtrl.root)
      _helixCtrl = null
    },
  }
}
