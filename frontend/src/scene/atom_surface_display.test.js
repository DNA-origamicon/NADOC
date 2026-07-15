import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

// The 3 region-overlay renderers are constructed INSIDE the factory via these
// imports — mock them so no real THREE scene is needed.
const _madeAtomRenderers = []
const _madeSurfaceRenderers = []
function makeAtomStub() {
  let mode = 'off'
  const stub = {
    getMode: vi.fn(() => mode),
    setMode: vi.fn((m) => { mode = m }),
    update: vi.fn(),
    dispose: vi.fn(),
    highlight: vi.fn(),
    setColorMode: vi.fn(),
    setVdwScale: vi.fn(),
    _setMode: (m) => { mode = m },
  }
  return stub
}
function makeSurfaceStub() {
  let mode = 'off'
  return {
    getMode: vi.fn(() => mode),
    setMode: vi.fn((m) => { mode = m }),
    update: vi.fn(),
    dispose: vi.fn(),
    highlight: vi.fn(),
    applyStrandColors: vi.fn(),
    setOpacity: vi.fn(),
    setColorMode: vi.fn(),
    _setMode: (m) => { mode = m },
  }
}
vi.mock('./atomistic_renderer.js', () => ({
  initAtomisticRenderer: vi.fn(() => { const s = makeAtomStub(); _madeAtomRenderers.push(s); return s }),
}))
vi.mock('./surface_renderer.js', () => ({
  initSurfaceRenderer: vi.fn(() => { const s = makeSurfaceStub(); _madeSurfaceRenderers.push(s); return s }),
}))
vi.mock('./design_queries.js', () => ({
  surfaceSegments: vi.fn(() => []),
}))
vi.mock('./representation_overrides.js', () => ({
  repColumnsByRep: vi.fn(() => ({ vdw: new Set(), ballstick: new Set() })),
}))

import { initAtomSurfaceDisplay, regionSurfaceSignature } from './atom_surface_display.js'
import { surfaceSegments } from './design_queries.js'

const DOM = [
  'surface-options-panel',
  'sl-surface-opacity', 'sv-surface-opacity',
  'sl-surface-probe', 'sv-surface-probe',
  'surface-color-strand', 'surface-color-uniform',
  'sl-atom-vdw-scale', 'sv-atom-vdw-scale',
  'repr-atom-radius-row',
]

function makeDeps(overrides = {}) {
  const root = { visible: true }
  return {
    scene: {},
    store: overrides.store ?? createMockStore({ currentDesign: null, currentGeometry: null }),
    api: { getRegionSurface: vi.fn(async () => ({})) },
    designRenderer: { getHelixCtrl: () => ({ root }) },
    atomisticRenderer: makeAtomStub(),
    surfaceRenderer: makeSurfaceStub(),
    unfoldView: { setArcsVisible: vi.fn(), refreshArcVisibility: vi.fn() },
    overhangLinkArcs: { setVisible: vi.fn() },
    _root: root,
    ...overrides,
  }
}

beforeEach(() => {
  clearDom()
  _madeAtomRenderers.length = 0
  _madeSurfaceRenderers.length = 0
  vi.clearAllMocks()
  global.fetch = vi.fn(async () => ({ ok: true, json: async () => ({ stats: {} }) }))
})

describe('regionSurfaceSignature (pure)', () => {
  it('joins helix:bp ranges sorted', () => {
    surfaceSegments.mockReturnValueOnce([
      { helix_id: 2, bp_start: 5, bp_end: 9 },
      { helix_id: 1, bp_start: 0, bp_end: 3 },
    ])
    expect(regionSurfaceSignature({})).toBe('1:0-3|2:5-9')
  })
  it('empty segments → empty string', () => {
    surfaceSegments.mockReturnValueOnce([])
    expect(regionSurfaceSignature({})).toBe('')
  })
})

describe('initAtomSurfaceDisplay', () => {
  it('returns the public API and builds 2 region atom + 1 region surface renderer', () => {
    mountIds(DOM)
    const api = initAtomSurfaceDisplay(makeDeps())
    for (const k of [
      'applySurfaceMode', 'applyAtomisticMode', 'setCGVisible', 'setSurfacePanelVisible',
      'setAtomisticSlidersVisible', 'getSurfaceMode', 'getSurfaceProbeRadius',
      'invalidateAtomCache', 'invalidateSurfaceCache',
      'getRegionVdwRenderer', 'getRegionBallstickRenderer', 'getRegionSurfaceRenderer',
    ]) expect(typeof api[k]).toBe('function')
    expect(_madeAtomRenderers.length).toBe(2)    // vdw + ballstick
    expect(_madeSurfaceRenderers.length).toBe(1) // region surface
  })

  it('no-ops gracefully when DOM is absent', () => {
    expect(() => initAtomSurfaceDisplay(makeDeps())).not.toThrow()
  })

  it('setSurfacePanelVisible toggles the panel display', () => {
    mountIds(DOM)
    const api = initAtomSurfaceDisplay(makeDeps())
    const panel = document.getElementById('surface-options-panel')
    api.setSurfacePanelVisible(true)
    expect(panel.style.display).toBe('')
    api.setSurfacePanelVisible(false)
    expect(panel.style.display).toBe('none')
  })

  it('setAtomisticSlidersVisible toggles the atom radius row', () => {
    mountIds(DOM)
    const api = initAtomSurfaceDisplay(makeDeps())
    api.setAtomisticSlidersVisible(false)
    expect(document.getElementById('repr-atom-radius-row').style.display).toBe('none')
    api.setAtomisticSlidersVisible(true)
    expect(document.getElementById('repr-atom-radius-row').style.display).toBe('')
  })

  it('surface opacity slider writes store.surfaceOpacity', () => {
    mountIds(DOM)
    const deps = makeDeps()
    initAtomSurfaceDisplay(deps)
    const sl = document.getElementById('sl-surface-opacity')
    sl.value = '0.42'
    sl.dispatchEvent(new Event('input'))
    expect(deps.store.getState().surfaceOpacity).toBeCloseTo(0.42)
    expect(document.getElementById('sv-surface-opacity').textContent).toBe('0.42')
  })

  it('probe slider updates getSurfaceProbeRadius; no re-apply while surface off', () => {
    mountIds(DOM)
    const deps = makeDeps()
    const api = initAtomSurfaceDisplay(deps)
    const sl = document.getElementById('sl-surface-probe')
    sl.value = '0.35'
    sl.dispatchEvent(new Event('input'))
    expect(api.getSurfaceProbeRadius()).toBeCloseTo(0.35)
    expect(deps.surfaceRenderer.update).not.toHaveBeenCalled() // surface mode is 'off'
  })

  it('surface colour buttons set store mode + active classes', () => {
    mountIds(DOM)
    const deps = makeDeps()
    initAtomSurfaceDisplay(deps)
    document.getElementById('surface-color-uniform').click()
    expect(deps.store.getState().surfaceColorMode).toBe('uniform')
    expect(document.getElementById('surface-color-uniform').classList.contains('active')).toBe(true)
    document.getElementById('surface-color-strand').click()
    expect(deps.store.getState().surfaceColorMode).toBe('strand')
    expect(document.getElementById('surface-color-strand').classList.contains('active')).toBe(true)
  })

  it('atom radius slider drives atomisticRenderer.setVdwScale', () => {
    mountIds(DOM)
    const deps = makeDeps()
    initAtomSurfaceDisplay(deps)
    const sl = document.getElementById('sl-atom-vdw-scale')
    sl.value = '1.25'
    sl.dispatchEvent(new Event('input'))
    expect(deps.atomisticRenderer.setVdwScale).toHaveBeenCalledWith(1.25)
  })

  it('setCGVisible drives helix root + arcs + link-arc visibility', () => {
    mountIds(DOM)
    const deps = makeDeps()
    const api = initAtomSurfaceDisplay(deps)
    api.setCGVisible(false)
    expect(deps._root.visible).toBe(false)
    expect(deps.unfoldView.setArcsVisible).toHaveBeenCalledWith(false)
    expect(deps.unfoldView.refreshArcVisibility).toHaveBeenCalled()
    expect(deps.overhangLinkArcs.setVisible).toHaveBeenCalledWith(false)
    api.setCGVisible(true)
    expect(deps._root.visible).toBe(true)
  })

  it('applyAtomisticMode(off) sets renderer off, restores CG, hides sliders', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    const api = initAtomSurfaceDisplay(deps)
    await api.applyAtomisticMode('off')
    expect(deps.atomisticRenderer.setMode).toHaveBeenCalledWith('off')
    expect(deps._root.visible).toBe(true) // setCGVisible(mode==='off') === true
    expect(document.getElementById('repr-atom-radius-row').style.display).toBe('none')
  })

  it('applyAtomisticMode(vdw) hides CG, fetches atom data once, updates renderer', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    const api = initAtomSurfaceDisplay(deps)
    await api.applyAtomisticMode('vdw')
    expect(deps.atomisticRenderer.setMode).toHaveBeenCalledWith('vdw')
    expect(deps._root.visible).toBe(false)
    expect(global.fetch).toHaveBeenCalledTimes(1)
    expect(deps.atomisticRenderer.update).toHaveBeenCalled()
    // second apply reuses the cache — no second fetch
    deps.atomisticRenderer._setMode('vdw')
    await api.applyAtomisticMode('vdw')
    expect(global.fetch).toHaveBeenCalledTimes(1)
  })

  it('applyAtomisticMode DEFERS to an active sim overlay: no native flash (keeps CG, skips design fetch)', async () => {
    mountIds(DOM)
    const deps = makeDeps({ getSimOverlayWillDriveAtomistic: () => true })
    const api = initAtomSurfaceDisplay(deps)
    await api.applyAtomisticMode('ballstick')
    expect(deps.atomisticRenderer.setMode).toHaveBeenCalledWith('ballstick')
    // CG stays up (relaxed shape) until the overlay lands; design atoms are NOT fetched.
    expect(deps._root.visible).toBe(true)
    expect(global.fetch).not.toHaveBeenCalled()
    expect(deps.atomisticRenderer.update).not.toHaveBeenCalled()
  })

  it('deferring to a sim overlay STILL sets the atomistic colour mode (keeps strand coloring, no cpk default)', async () => {
    mountIds(DOM)
    const store = createMockStore({ currentDesign: null, currentGeometry: null, coloringMode: 'strand' })
    const deps = makeDeps({ store, getSimOverlayWillDriveAtomistic: () => true })
    const api = initAtomSurfaceDisplay(deps)
    await api.applyAtomisticMode('ballstick')
    // Colour mode applied from the global coloringMode even though the design-atoms
    // fetch was skipped — the overlay's later atom rebuild re-applies this persistent mode.
    expect(deps.atomisticRenderer.setColorMode).toHaveBeenCalledWith('strand', expect.anything())
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('applyAtomisticMode does NOT defer when no overlay drives atomistic (normal design view)', async () => {
    mountIds(DOM)
    const deps = makeDeps({ getSimOverlayWillDriveAtomistic: () => false })
    const api = initAtomSurfaceDisplay(deps)
    await api.applyAtomisticMode('ballstick')
    expect(deps._root.visible).toBe(false)         // CG hidden
    expect(global.fetch).toHaveBeenCalledTimes(1)  // design atoms fetched
    expect(deps.atomisticRenderer.update).toHaveBeenCalled()
  })

  it('applySurfaceMode reflects in getSurfaceMode and fetches the surface', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    const api = initAtomSurfaceDisplay(deps)
    await api.applySurfaceMode('on')
    expect(api.getSurfaceMode()).toBe('on')
    expect(global.fetch).toHaveBeenCalled()
    expect(deps.surfaceRenderer.update).toHaveBeenCalled()
    await api.applySurfaceMode('off')
    expect(api.getSurfaceMode()).toBe('off')
    expect(deps.surfaceRenderer.dispose).toHaveBeenCalled()
  })

  it('strandColors change refreshes atom + surface colours only when active', () => {
    mountIds(DOM)
    const store = createMockStore({
      currentDesign: null, currentGeometry: null, strandColors: {}, coloringMode: 'strand',
    })
    const deps = makeDeps({ store })
    initAtomSurfaceDisplay(deps)
    // atom mode off, surface off → no colour refresh
    store.setState({ strandColors: { s1: '#fff' } })
    expect(deps.atomisticRenderer.setColorMode).not.toHaveBeenCalled()
    // turn atom mode on → next change refreshes
    deps.atomisticRenderer._setMode('vdw')
    store.setState({ strandColors: { s1: '#000' } })
    expect(deps.atomisticRenderer.setColorMode).toHaveBeenCalled()
  })

  it('design change invalidates atom cache → next apply re-fetches', async () => {
    mountIds(DOM)
    const store = createMockStore({ currentDesign: { a: 1 }, currentGeometry: null })
    const deps = makeDeps({ store })
    const api = initAtomSurfaceDisplay(deps)
    await api.applyAtomisticMode('vdw')
    expect(global.fetch).toHaveBeenCalledTimes(1)
    // design change → cache invalidated by the subscriber
    deps.atomisticRenderer._setMode('vdw')
    store.setState({ currentDesign: { a: 2 } })
    // subscriber re-applies on design change (designChanged path); allow microtasks
    await Promise.resolve()
    expect(global.fetch.mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})
