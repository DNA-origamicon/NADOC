/**
 * Tests for ui/tool_filter_toggles.js — the `#view-tools .sf-btn[data-key]`
 * filter-button row factory and its toolFilters→renderer-visibility subscriber.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initToolFilterToggles } from './tool_filter_toggles.js'

const KEYS = [
  ['bluntEnds',          'blunt'],
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
    overhangLocations: { setVisible: vi.fn() },
    designRenderer: { setExtensionsVisible: vi.fn() },
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

    buttons.ovhg.click()
    expect(store.getState().toolFilters.overhangLocations).toBe(true)
    buttons.ovhg.click()
    expect(store.getState().toolFilters.overhangLocations).toBe(false)
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
    expect(deps.overhangLocations.setVisible).not.toHaveBeenCalled()
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
