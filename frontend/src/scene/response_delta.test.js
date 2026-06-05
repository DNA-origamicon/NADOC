/**
 * Tests for scene/response_delta.js — the backend response-delta application
 * subsystem extracted from main.js (undo/redo/seek in-place renderer updates).
 */
import { describe, it, expect, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { rebakeHelixAxesForClusterDelta, initResponseDelta } from './response_delta.js'

const IDENT = { pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, 0, 1] }
const close = (a, b, eps = 1e-6) => Math.abs(a - b) < eps

describe('rebakeHelixAxesForClusterDelta (pure)', () => {
  it('no-ops on null axes / empty helixIds / missing ct (no throw)', () => {
    expect(() => rebakeHelixAxesForClusterDelta(null, ['h1'], IDENT, IDENT)).not.toThrow()
    expect(() => rebakeHelixAxesForClusterDelta({ h1: {} }, [], IDENT, IDENT)).not.toThrow()
    expect(() => rebakeHelixAxesForClusterDelta({ h1: {} }, ['h1'], null, IDENT)).not.toThrow()
    expect(() => rebakeHelixAxesForClusterDelta({ h1: {} }, ['h1'], IDENT, null)).not.toThrow()
  })

  it('identity delta leaves points unchanged', () => {
    const axes = { h1: { start: [5, 0, 0], end: [5, 0, 1] } }
    rebakeHelixAxesForClusterDelta(axes, ['h1'], IDENT, IDENT)
    expect(axes.h1.start.map(v => +v.toFixed(6))).toEqual([5, 0, 0])
    expect(axes.h1.end.map(v => +v.toFixed(6))).toEqual([5, 0, 1])
  })

  it('pure translation shifts every point by Δtranslation', () => {
    const axes = { h1: { start: [5, 0, 0], end: [5, 0, 1] } }
    const newCt = { pivot: [0, 0, 0], translation: [1, 2, 3], rotation: [0, 0, 0, 1] }
    rebakeHelixAxesForClusterDelta(axes, ['h1'], IDENT, newCt)
    expect(axes.h1.start.map(v => +v.toFixed(6))).toEqual([6, 2, 3])
    expect(axes.h1.end.map(v => +v.toFixed(6))).toEqual([6, 2, 4])
  })

  it('90° rotation about origin pivot rotates points (start [1,0,0] → [0,1,0])', () => {
    const s = Math.SQRT1_2 // sin/cos of 45° → quat for 90° about Z is (0,0,sin45,cos45)
    const axes = { h1: { start: [1, 0, 0] } }
    const newCt = { pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, s, s] }
    rebakeHelixAxesForClusterDelta(axes, ['h1'], IDENT, newCt)
    expect(close(axes.h1.start[0], 0)).toBe(true)
    expect(close(axes.h1.start[1], 1)).toBe(true)
    expect(close(axes.h1.start[2], 0)).toBe(true)
  })

  it('rebakes samples, segments and ovhgAxes (direction via xformDir)', () => {
    const s = Math.SQRT1_2
    const axes = {
      h1: {
        start: [1, 0, 0],
        samples: [[1, 0, 0], [2, 0, 0]],
        segments: [{ id: 'a', start: [1, 0, 0], end: [2, 0, 0] }],
        ovhgAxes: { o1: { start: [1, 0, 0], direction: [1, 0, 0] } },
      },
    }
    const newCt = { pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, s, s] }
    rebakeHelixAxesForClusterDelta(axes, ['h1'], IDENT, newCt)
    expect(close(axes.h1.samples[0][1], 1)).toBe(true)
    expect(close(axes.h1.segments[0].end[1], 2)).toBe(true)
    expect(axes.h1.segments[0].id).toBe('a') // spread preserves other fields
    // direction is a pure rotation (no pivot/translation) → [1,0,0] → [0,1,0]
    expect(close(axes.h1.ovhgAxes.o1.direction[0], 0)).toBe(true)
    expect(close(axes.h1.ovhgAxes.o1.direction[1], 1)).toBe(true)
  })

  it('skips helix ids not present in the axes map', () => {
    const axes = { h1: { start: [1, 0, 0] } }
    expect(() => rebakeHelixAxesForClusterDelta(axes, ['h1', 'missing'], IDENT, IDENT)).not.toThrow()
  })
})

function makeHelixCtrl() {
  return {
    captureClusterBase: vi.fn(),
    applyClusterTransform: vi.fn(),
    commitClusterPositions: vi.fn(),
    applyBridgeNucsUpdate: vi.fn(),
    applyPositionsUpdate: vi.fn(),
  }
}

function makeDeps(initialState = {}, { helixCtrl = makeHelixCtrl(), jointRenderer = { rebuildHulls: vi.fn() } } = {}) {
  const store = createMockStore(initialState)
  const api = { refreshBridges: vi.fn().mockResolvedValue([]), registerResponseDeltaHandler: vi.fn() }
  const designRenderer = {
    getHelixCtrl: vi.fn(() => helixCtrl),
    applyClusterCrossoverUpdate: vi.fn(),
  }
  return {
    deps: {
      store, api, designRenderer,
      getJointRenderer: () => jointRenderer,
      bluntEnds: {},
      unfoldView: { applyClusterArcUpdate: vi.fn(), applyClusterExtArcUpdate: vi.fn() },
      flexibleArcs: { rebuild: vi.fn() },
      overhangLinkArcs: { rebuild: vi.fn() },
      overhangLocations: { isVisible: () => false, rebuild: vi.fn() },
      overhangNameOverlay: { isVisible: () => false, rebuild: vi.fn() },
      loopSkipHighlight: { isVisible: () => false, rebuild: vi.fn() },
      unligatedCrossoverMarkers: { rebuild: vi.fn() },
    },
    helixCtrl, jointRenderer, store,
  }
}

const clusterState = {
  currentDesign: { cluster_transforms: [{ id: 'c1', helix_ids: ['h1'] }], helices: [{ id: 'h1' }] },
  currentGeometry: [{}],
  currentHelixAxes: { h1: { start: [0, 0, 0], end: [0, 0, 1] } },
  unligatedCrossoverIds: [],
}

const clusterDiff = {
  cluster_id: 'c1', helix_ids: ['h1'],
  old_rotation: [0, 0, 0, 1], new_rotation: [0, 0, 0, 1],
  old_pivot: [0, 0, 0], new_pivot: [0, 0, 0],
  old_translation: [0, 0, 0], new_translation: [1, 0, 0],
}

describe('initResponseDelta', () => {
  it('returns the expected API surface', () => {
    const { deps } = makeDeps()
    const rd = initResponseDelta(deps)
    expect(typeof rd.applyResponseDelta).toBe('function')
    expect(typeof rd.applyClusterUndoRedoDeltas).toBe('function')
    expect(typeof rd.applyPositionsOnlyDiff).toBe('function')
    expect(typeof rd.rebakeHelixAxesForClusterDelta).toBe('function')
  })

  it('applyResponseDelta ignores unknown diff_kind and returns result verbatim', async () => {
    const { deps, helixCtrl } = makeDeps()
    const rd = initResponseDelta(deps)
    const result = { diff_kind: 'full', foo: 1 }
    expect(await rd.applyResponseDelta(result)).toBe(result)
    expect(helixCtrl.applyClusterTransform).not.toHaveBeenCalled()
  })

  it('cluster_only diff drives the applyClusterTransform pipeline + rebuildHulls + refreshBridges', async () => {
    const { deps, helixCtrl, jointRenderer, store } = makeDeps(clusterState)
    const rd = initResponseDelta(deps)
    await rd.applyResponseDelta({ diff_kind: 'cluster_only', cluster_diffs: [clusterDiff] })

    expect(helixCtrl.applyClusterTransform).toHaveBeenCalledTimes(1)
    const [hids, oldOrigin, newOrigin, , extra] = helixCtrl.applyClusterTransform.mock.calls[0]
    expect(hids).toEqual(['h1'])
    expect([oldOrigin.x, oldOrigin.y, oldOrigin.z]).toEqual([0, 0, 0])
    expect([newOrigin.x, newOrigin.y, newOrigin.z]).toEqual([1, 0, 0])
    expect(extra).toBeNull()
    expect(helixCtrl.commitClusterPositions).toHaveBeenCalledWith(['h1'])
    expect(deps.api.refreshBridges).toHaveBeenCalledWith(['c1'])
    expect(jointRenderer.rebuildHulls).toHaveBeenCalledWith(store.getState().currentDesign)
    // axes rebaked in place (no domain_ids → rebake ran) → start shifts +x
    expect(store.getState().currentHelixAxes.h1.start.map(v => +v.toFixed(6))).toEqual([1, 0, 0])
  })

  it('cluster move with domain_ids skips the axis rebake (no rebuildHulls)', async () => {
    const state = {
      ...clusterState,
      currentDesign: { cluster_transforms: [{ id: 'c1', helix_ids: ['h1'], domain_ids: ['d1'] }], helices: [{ id: 'h1' }] },
      currentHelixAxes: { h1: { start: [0, 0, 0] } },
    }
    const { deps, jointRenderer } = makeDeps(state)
    const rd = initResponseDelta(deps)
    await rd.applyResponseDelta({ diff_kind: 'cluster_only', cluster_diffs: [clusterDiff] })
    expect(jointRenderer.rebuildHulls).not.toHaveBeenCalled()
    expect(deps.store.getState().currentHelixAxes.h1.start).toEqual([0, 0, 0]) // unchanged
  })

  it('applyClusterUndoRedoDeltas no-ops on empty array or missing helixCtrl', async () => {
    const { deps, helixCtrl } = makeDeps(clusterState)
    const rd = initResponseDelta(deps)
    await rd.applyClusterUndoRedoDeltas([])
    expect(helixCtrl.captureClusterBase).not.toHaveBeenCalled()

    const noCtrl = makeDeps(clusterState, { helixCtrl: makeHelixCtrl() })
    noCtrl.deps.designRenderer.getHelixCtrl = vi.fn(() => null)
    const rd2 = initResponseDelta(noCtrl.deps)
    await rd2.applyClusterUndoRedoDeltas([clusterDiff])
    expect(noCtrl.helixCtrl.commitClusterPositions).not.toHaveBeenCalled()
  })

  it('positions_only diff calls applyPositionsUpdate + cross-helix arc refresh', () => {
    const state = {
      currentDesign: { helices: [{ id: 'h1' }, { id: 'h2' }] },
      currentGeometry: [{}],
      currentHelixAxes: {},
      unligatedCrossoverIds: [],
    }
    const { deps, helixCtrl } = makeDeps(state)
    const rd = initResponseDelta(deps)
    rd.applyPositionsOnlyDiff({ positions_by_helix: { h1: [] }, helix_axes: { h1: {} } })
    expect(helixCtrl.applyPositionsUpdate).toHaveBeenCalledWith({ h1: [] }, { h1: {} })
    expect(deps.designRenderer.applyClusterCrossoverUpdate).toHaveBeenCalledWith(['h1', 'h2'])
    expect(deps.flexibleArcs.rebuild).toHaveBeenCalledWith(state.currentDesign)
  })

  it('positions_only with no helixCtrl no-ops', () => {
    const { deps } = makeDeps({ currentDesign: { helices: [] } })
    deps.designRenderer.getHelixCtrl = vi.fn(() => null)
    const rd = initResponseDelta(deps)
    expect(() => rd.applyPositionsOnlyDiff({ positions_by_helix: {} })).not.toThrow()
  })

  it('rebakeHelixAxesForClusterDelta method reads store axes and mutates in place', () => {
    const { deps, store } = makeDeps({ currentHelixAxes: { h1: { start: [5, 0, 0] } } })
    const rd = initResponseDelta(deps)
    const newCt = { pivot: [0, 0, 0], translation: [1, 0, 0], rotation: [0, 0, 0, 1] }
    rd.rebakeHelixAxesForClusterDelta(['h1'], IDENT, newCt)
    expect(store.getState().currentHelixAxes.h1.start.map(v => +v.toFixed(6))).toEqual([6, 0, 0])
  })
})
