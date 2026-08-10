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
    setCrispZones: vi.fn(),
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
  'sl-surface-probe', 'sv-surface-probe', 'cb-surface-figure-quality',
  'surface-color-strand', 'surface-color-uniform',
  'sl-atom-vdw-scale', 'sv-atom-vdw-scale',
  'repr-atom-radius-row',
]

function makeDeps(overrides = {}) {
  const root = { visible: true }
  // Mirrors design_renderer: setDesignVisible records the intent in _designVisible AND
  // applies it, and every _rebuild re-applies that flag to the freshly-allocated root.
  const dr = {
    _designVisible: true,
    getHelixCtrl: () => ({ root }),
    setDesignVisible(v) { dr._designVisible = v; root.visible = v },
    /** Stand-in for any _rebuild path (e.g. setExtraNucleotides): new root, visible=true,
     *  then the hidden state is re-applied. */
    _simulateRebuild() { root.visible = true; if (!dr._designVisible) root.visible = false },
  }
  return {
    scene: {},
    store: overrides.store ?? createMockStore({ currentDesign: null, currentGeometry: null }),
    api: { getRegionSurface: vi.fn(async () => ({})) },
    designRenderer: dr,
    atomisticRenderer: makeAtomStub(),
    surfaceRenderer: makeSurfaceStub(),
    unfoldView: { setArcsVisible: vi.fn(), refreshArcVisibility: vi.fn() },
    overhangLinkArcs: { setVisible: vi.fn() },
    _root: root,
    _dr: dr,
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
      'setAtomisticSlidersVisible', 'setOverlayMode', 'getSurfaceMode', 'getSurfaceProbeRadius',
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

  it('overlay mode keeps CG visible while atomistic mode is active', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    const api = initAtomSurfaceDisplay(deps)

    api.setOverlayMode(true)
    await api.applyAtomisticMode('ballstick')
    expect(deps._root.visible).toBe(true)

    // Heavy trajectory/simulation callbacks normally request CG hidden.
    api.setCGVisible(false)
    expect(deps._root.visible).toBe(true)

    api.setOverlayMode(false)
    expect(deps._root.visible).toBe(false)
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

  it('figure-quality preset owns detail and probe controls, then restores them', () => {
    mountIds(DOM)
    const api = initAtomSurfaceDisplay(makeDeps())
    const preset = document.getElementById('cb-surface-figure-quality')
    const probe = document.getElementById('sl-surface-probe')

    preset.checked = true
    preset.dispatchEvent(new Event('change'))
    expect(api.getSurfaceParams()).toMatchObject({ detail: 'chimerax' })
    expect(probe.disabled).toBe(true)
    expect(document.getElementById('sv-surface-probe').textContent).toBe('0.14')

    preset.checked = false
    preset.dispatchEvent(new Event('change'))
    expect(api.getSurfaceParams()).toMatchObject({ detail: 'coarse' })
    expect(probe.disabled).toBe(false)
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

  // Regression: setCGVisible used to poke root.visible directly, leaving the renderer's
  // _designVisible stale at true. Any later rebuild (the oxDNA capture-strand injection
  // calls setExtraNucleotides → _rebuild) then resurrected the CG model on top of the
  // atomistic rep, and it stayed up until the multi-second atom build landed — which
  // reads to the user as "the Full rep came back / NADOC is broken".
  it('a rebuild after setCGVisible(false) leaves the CG hidden', () => {
    mountIds(DOM)
    const deps = makeDeps()
    const api = initAtomSurfaceDisplay(deps)
    api.setCGVisible(false)
    expect(deps._dr._designVisible).toBe(false)   // intent recorded, not just the root poked
    deps._dr._simulateRebuild()
    expect(deps._root.visible).toBe(false)
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
    const deps = makeDeps({ getSimOverlayWillDriveHeavy: () => true })
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
    const deps = makeDeps({ store, getSimOverlayWillDriveHeavy: () => true })
    const api = initAtomSurfaceDisplay(deps)
    await api.applyAtomisticMode('ballstick')
    // Colour mode applied from the global coloringMode even though the design-atoms
    // fetch was skipped — the overlay's later atom rebuild re-applies this persistent mode.
    expect(deps.atomisticRenderer.setColorMode).toHaveBeenCalledWith('strand', expect.anything())
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('applyAtomisticMode does NOT defer when no overlay drives atomistic (normal design view)', async () => {
    mountIds(DOM)
    const deps = makeDeps({ getSimOverlayWillDriveHeavy: () => false })
    const api = initAtomSurfaceDisplay(deps)
    await api.applyAtomisticMode('ballstick')
    expect(deps._root.visible).toBe(false)         // CG hidden
    expect(global.fetch).toHaveBeenCalledTimes(1)  // design atoms fetched
    expect(deps.atomisticRenderer.update).toHaveBeenCalled()
  })

  // The predicate is asked PER KIND, and the kind is load-bearing, not decoration: the live
  // "Display MD" stream drives atomistic and never a surface, and a NAMD flexibility map
  // drives neither.  A caller that drops the argument defers the surface to an overlay that
  // will never deliver one — a permanently blank surface, which is worse than the flash.
  it('asks getSimOverlayWillDriveHeavy for the specific kind being built', async () => {
    mountIds(DOM)
    const seen = []
    const deps = makeDeps({ getSimOverlayWillDriveHeavy: (kind) => { seen.push(kind); return false } })
    const api = initAtomSurfaceDisplay(deps)
    await api.applyAtomisticMode('ballstick')
    await api.applySurfaceMode('on')
    expect(seen).toContain('atomistic')
    expect(seen).toContain('surface')
    expect(seen).not.toContain(undefined)
  })

  it('an overlay that drives ONLY atomistic does not make the surface defer', async () => {
    mountIds(DOM)
    const deps = makeDeps({ getSimOverlayWillDriveHeavy: (kind) => kind === 'atomistic' })
    const api = initAtomSurfaceDisplay(deps)
    await api.applySurfaceMode('on')
    // Design surface IS computed — nothing else is going to produce one.
    expect(global.fetch).toHaveBeenCalledTimes(1)
    expect(deps._root.visible).toBe(false)
  })

  it('applySurfaceMode DEFERS to an active sim overlay: no native flash (keeps CG, skips design surface fetch)', async () => {
    mountIds(DOM)
    const deps = makeDeps({ getSimOverlayWillDriveHeavy: () => true })
    const api = initAtomSurfaceDisplay(deps)
    await api.applySurfaceMode('on')
    expect(api.getSurfaceMode()).toBe('on')
    expect(deps._root.visible).toBe(true)          // relaxed CG stays up
    expect(global.fetch).not.toHaveBeenCalled()    // design surface NOT computed
    // Renderer activated with an empty mesh (mode 'on' + a mesh) so the overlay's push
    // can populate it — without this _pushSurface bails and nothing renders.
    expect(deps.surfaceRenderer.update).toHaveBeenCalledWith({ vertices: [], faces: [] }, expect.anything())
  })

  it('changing probe radius while a sim overlay owns the surface re-generates the OVERLAY (not a design fetch, no revert)', async () => {
    mountIds(DOM)
    const onSurfaceParamsChanged = vi.fn()
    const deps = makeDeps({ getSimOverlayWillDriveHeavy: () => true, onSurfaceParamsChanged })
    const api = initAtomSurfaceDisplay(deps)
    await api.applySurfaceMode('on')               // defer path → surfaceMode 'on'
    global.fetch.mockClear()
    deps.surfaceRenderer.update.mockClear()
    const probe = document.getElementById('sl-surface-probe')
    probe.value = '0.4'
    probe.dispatchEvent(new Event('input'))
    expect(onSurfaceParamsChanged).toHaveBeenCalled()          // overlay regen triggered
    expect(global.fetch).not.toHaveBeenCalled()                // NOT the design-surface path
    expect(deps.surfaceRenderer.update).not.toHaveBeenCalled() // not blanked to an empty mesh
    expect(api.getSurfaceParams().probe_radius).toBeCloseTo(0.4)  // new radius exposed to the overlay fetch
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

  it('discards a pre-edit atom response that finishes after the post-edit model', async () => {
    mountIds(DOM)
    const pending = []
    global.fetch = vi.fn(() => new Promise(resolve => pending.push(resolve)))
    const store = createMockStore({ currentDesign: { revision: 1 }, currentGeometry: null })
    const deps = makeDeps({ store })
    const api = initAtomSurfaceDisplay(deps)

    const oldApply = api.applyAtomisticMode('ballstick')
    await vi.waitFor(() => expect(pending).toHaveLength(1))

    // Committing a nucleotide pose replaces currentDesign and starts the authoritative
    // post-edit build while the pre-edit request is still in flight.
    deps.atomisticRenderer._setMode('ballstick')
    store.setState({ currentDesign: { revision: 2 } })
    await vi.waitFor(() => expect(pending).toHaveLength(2))

    pending[1]({ ok: true, json: async () => ({ revision: 2, atoms: [], bonds: [] }) })
    await vi.waitFor(() => expect(deps.atomisticRenderer.update).toHaveBeenCalledTimes(1))
    expect(deps.atomisticRenderer.update).toHaveBeenLastCalledWith(
      expect.objectContaining({ revision: 2 }),
    )

    // The old build arrives last. It must not repaint or enter the cache.
    pending[0]({ ok: true, json: async () => ({ revision: 1, atoms: [], bonds: [] }) })
    await oldApply
    await Promise.resolve()
    expect(deps.atomisticRenderer.update).toHaveBeenCalledTimes(1)
  })
})
