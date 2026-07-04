/**
 * md_panel.test.js — representation-persistence of the live "Display MD" controller.
 *
 * The controller stops a live display through THREE entry points (`stopDisplayKeepWarm`,
 * `stopAndRestore`, and the WebSocket `onclose`), all of which funnel into the private
 * `_restoreDesign`.  The invariant these tests pin: stopping a display must revert to the
 * design's equilibrium pose WITHOUT changing the user's chosen scene representation —
 * an atomistic/surface scene must NOT fall back to the CG bead-and-slab model (the bug),
 * and a CG scene must show the native design.
 *
 * We drive the real factory with mock renderers + a stubbed scene representation (set via
 * the `nadoc:representation-change` event the panel already listens to), and assert which
 * renderer calls fire on stop.  DOM is the minimal by-id set the factory touches unguarded.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { initMdPanel } from './md_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

function setSceneRepr(repr) {
  window.dispatchEvent(new CustomEvent('nadoc:representation-change', {
    detail: { representation: repr },
  }))
}

function makeDeps() {
  return {
    designRenderer: {
      setDesignVisible: vi.fn(),
      applyFemPositions: vi.fn(),
    },
    mdOverlay: { dispose: vi.fn() },
    atomisticRenderer: {
      setMode: vi.fn(),
      getMode: vi.fn(() => 'ballstick'),
      update: vi.fn(),
    },
    onRestoreDesignHeavy: vi.fn(),
  }
}

let store, deps, ctrl, dom

beforeEach(() => {
  dom = mountIds({
    'md-panel': 'div',
    'md-panel-heading': 'div',
    'md-panel-body': 'div',
    'md-panel-arrow': 'div',
    'md-show-nadoc': 'input',
  })
  dom['md-show-nadoc'].type = 'checkbox'
  store = createMockStore({ currentDesign: { id: 'd1' } })
  deps = makeDeps()
  ctrl = initMdPanel(store, deps)
})

afterEach(() => clearDom())

// Both explicit stop entry points funnel into the same _restoreDesign; assert both.
for (const stop of ['stopDisplayKeepWarm', 'stopAndRestore']) {
  describe(`${stop} — representation persists`, () => {
    it('atomistic scene: keeps the heavy rep (rebuild), never shows native CG beads', () => {
      setSceneRepr('ballstick')
      deps.designRenderer.setDesignVisible.mockClear()
      deps.atomisticRenderer.setMode.mockClear()

      ctrl[stop]()

      // The chosen atomistic rep is rebuilt from the design at equilibrium…
      expect(deps.onRestoreDesignHeavy).toHaveBeenCalledTimes(1)
      // …the CG bead design stays hidden…
      expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(false)
      expect(deps.designRenderer.setDesignVisible).not.toHaveBeenCalledWith(true)
      // …and the atomistic renderer is NOT turned off (that was the revert bug).
      expect(deps.atomisticRenderer.setMode).not.toHaveBeenCalledWith('off')
      // MD-displaced positions are always dropped.
      expect(deps.designRenderer.applyFemPositions).toHaveBeenCalledWith(null)
    })

    it('surface scene: keeps the heavy rep (rebuild), hides native CG beads', () => {
      setSceneRepr('surface')
      deps.designRenderer.setDesignVisible.mockClear()

      ctrl[stop]()

      expect(deps.onRestoreDesignHeavy).toHaveBeenCalledTimes(1)
      expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(false)
      expect(deps.designRenderer.setDesignVisible).not.toHaveBeenCalledWith(true)
    })

    it('CG scene (full): shows the native design, turns atomistic off, no heavy rebuild', () => {
      setSceneRepr('full')
      deps.designRenderer.setDesignVisible.mockClear()
      deps.atomisticRenderer.setMode.mockClear()

      ctrl[stop]()

      expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(true)
      expect(deps.atomisticRenderer.setMode).toHaveBeenCalledWith('off')
      expect(deps.onRestoreDesignHeavy).not.toHaveBeenCalled()
    })

    it('hull-prism scene: treated as a design-renderer CG rep (native shown, no heavy rebuild)', () => {
      // hull-prism is drawn by the design renderer, so stopping must show the native
      // design — NOT hide it as if it were a heavy rep.
      setSceneRepr('hull-prism')
      deps.designRenderer.setDesignVisible.mockClear()

      ctrl[stop]()

      expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(true)
      expect(deps.onRestoreDesignHeavy).not.toHaveBeenCalled()
    })
  })
}

describe('representation switch while stopped keeps the scene repr in sync', () => {
  it('a later stop reflects the most-recent representation choice', () => {
    // Start atomistic, switch to CG, then stop → CG behaviour (native shown).
    setSceneRepr('ballstick')
    setSceneRepr('full')
    ctrl.stopDisplayKeepWarm()
    expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(true)
    expect(deps.onRestoreDesignHeavy).not.toHaveBeenCalled()
  })
})
