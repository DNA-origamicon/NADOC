/**
 * Tests for ui/tool_filter_toggles.js — the `#view-tools .sf-btn[data-key]`
 * filter-button row factory and its toolFilters→renderer-visibility subscriber.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initToolFilterToggles } from './tool_filter_toggles.js'

const KEYS = [
  ['bluntEnds',          'blunt'],
  ['crossoverLocations', 'xloc' ],
  ['overhangLocations',  'ovhg' ],
]

function mountDom() {
  document.body.innerHTML = ''
  const wrap = document.createElement('div')
  wrap.id = 'view-tools'
  const buttons = {}
  for (const [, dataKey] of KEYS) {
    const b = document.createElement('button')
    b.className = 'sf-btn'
    b.setAttribute('data-key', dataKey)
    wrap.appendChild(b)
    buttons[dataKey] = b
  }
  document.body.appendChild(wrap)
  return buttons
}

function makeDeps(initialState = {}) {
  const store = createMockStore({
    toolFilters: {},
    currentGeometry: { id: 'g' },
    assemblyActive: false,
    ...initialState,
  })
  const overhangHoverPicker = { reset: vi.fn() }
  const deps = {
    store,
    crossoverLocations: { setVisible: vi.fn(), rebuild: vi.fn(() => Promise.resolve()) },
    overhangLocations: { setVisible: vi.fn() },
    designRenderer: { setExtensionsVisible: vi.fn() },
    cadnanoView: { isActive: vi.fn(() => false), reapplyPositions: vi.fn() },
    unfoldView: { reapplyIfActive: vi.fn() },
    rebuildOverhangLocations: vi.fn(),
    getOverhangHoverPicker: () => overhangHoverPicker,
  }
  return { store, deps, overhangHoverPicker }
}

beforeEach(() => { document.body.innerHTML = '' })

describe('initToolFilterToggles — buttons', () => {
  it('no-ops (no throw) when the #view-tools buttons are absent', () => {
    const { deps } = makeDeps()
    expect(() => initToolFilterToggles(deps)).not.toThrow()
  })

  it('clicking a button flips its toolFilters key', () => {
    const buttons = mountDom()
    const { store, deps } = makeDeps()
    initToolFilterToggles(deps)

    buttons.xloc.click()
    expect(store.getState().toolFilters.crossoverLocations).toBe(true)
    buttons.xloc.click()
    expect(store.getState().toolFilters.crossoverLocations).toBe(false)
  })

  it('a button reflects its store key via the .active class on state change', () => {
    const buttons = mountDom()
    const { store, deps } = makeDeps()
    initToolFilterToggles(deps)

    store.setState({ toolFilters: { overhangLocations: true } })
    expect(buttons.ovhg.classList.contains('active')).toBe(true)
    store.setState({ toolFilters: { overhangLocations: false } })
    expect(buttons.ovhg.classList.contains('active')).toBe(false)
  })
})

describe('initToolFilterToggles — visibility subscriber', () => {
  it('early-returns when the toolFilters reference is unchanged', () => {
    mountDom()
    const { store, deps } = makeDeps()
    initToolFilterToggles(deps)

    store.setState({ assemblyActive: true }) // toolFilters ref untouched
    expect(deps.crossoverLocations.setVisible).not.toHaveBeenCalled()
    expect(deps.overhangLocations.setVisible).not.toHaveBeenCalled()
  })

  it('crossover ON → setVisible(true) + rebuild + unfold reapply (cadnano inactive)', async () => {
    mountDom()
    const { store, deps } = makeDeps()
    initToolFilterToggles(deps)

    store.setState({ toolFilters: { crossoverLocations: true } })
    expect(deps.crossoverLocations.setVisible).toHaveBeenCalledWith(true)
    expect(deps.crossoverLocations.rebuild).toHaveBeenCalledWith(store.getState().currentGeometry)
    await Promise.resolve()
    expect(deps.unfoldView.reapplyIfActive).toHaveBeenCalled()
    expect(deps.cadnanoView.reapplyPositions).not.toHaveBeenCalled()
  })

  it('crossover ON → cadnano reapply when cadnano is active', async () => {
    mountDom()
    const { store, deps } = makeDeps()
    deps.cadnanoView.isActive = vi.fn(() => true)
    initToolFilterToggles(deps)

    store.setState({ toolFilters: { crossoverLocations: true } })
    await Promise.resolve()
    expect(deps.cadnanoView.reapplyPositions).toHaveBeenCalled()
    expect(deps.unfoldView.reapplyIfActive).not.toHaveBeenCalled()
  })

  it('crossover OFF → setVisible(false), no rebuild', () => {
    mountDom()
    const { store, deps } = makeDeps({ toolFilters: { crossoverLocations: true } })
    initToolFilterToggles(deps)

    store.setState({ toolFilters: { crossoverLocations: false } })
    expect(deps.crossoverLocations.setVisible).toHaveBeenCalledWith(false)
    expect(deps.crossoverLocations.rebuild).not.toHaveBeenCalled()
  })

  it('overhang ON → setVisible(true) + rebuildOverhangLocations', () => {
    mountDom()
    const { store, deps } = makeDeps()
    initToolFilterToggles(deps)

    store.setState({ toolFilters: { overhangLocations: true } })
    expect(deps.overhangLocations.setVisible).toHaveBeenCalledWith(true)
    expect(deps.rebuildOverhangLocations).toHaveBeenCalled()
  })

  it('overhang OFF in assembly mode → hover picker reset', () => {
    mountDom()
    const { store, deps, overhangHoverPicker } = makeDeps({
      toolFilters: { overhangLocations: true }, assemblyActive: true,
    })
    initToolFilterToggles(deps)

    store.setState({ toolFilters: { overhangLocations: false } })
    expect(deps.overhangLocations.setVisible).toHaveBeenCalledWith(false)
    expect(overhangHoverPicker.reset).toHaveBeenCalled()
    expect(deps.rebuildOverhangLocations).not.toHaveBeenCalled()
  })

  it('overhang OFF outside assembly mode → no hover-picker reset', () => {
    mountDom()
    const { store, deps, overhangHoverPicker } = makeDeps({
      toolFilters: { overhangLocations: true }, assemblyActive: false,
    })
    initToolFilterToggles(deps)

    store.setState({ toolFilters: { overhangLocations: false } })
    expect(overhangHoverPicker.reset).not.toHaveBeenCalled()
  })

  it('extensionLocations change → designRenderer.setExtensionsVisible', () => {
    mountDom()
    const { store, deps } = makeDeps()
    initToolFilterToggles(deps)

    store.setState({ toolFilters: { extensionLocations: true } })
    expect(deps.designRenderer.setExtensionsVisible).toHaveBeenCalledWith(true)
  })
})
