/**
 * Unit tests for the View-menu pill-state controller.
 *
 *   initViewMenuPills — factory wiring: one store subscriber that mirrors
 *   store-backed view toggles onto View-menu pill chrome (via the injected
 *   setMenuToggle) + 3 visibility helpers (assembly/tools swap, import-item
 *   show/hide, deform-enabled gate). Pure DOM/state, no pure core.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initViewMenuPills } from './view_menu_pills.js'

// All ids the factory touches WITHOUT optional chaining must exist or it throws.
const mountChrome = () => mountIds({
  'menu-item-assembly': 'li',
  'menu-item-tools': 'li',
  'menu-view-slice': 'div',
  'menu-view-unfold': 'div',
  'menu-view-cadnano': 'div',
  'menu-file-import-cadnano': 'div',
  'menu-file-import-scadnano': 'div',
  'menu-view-deform': 'div',
  'mode-indicator': 'div',
})

beforeEach(() => clearDom())

describe('initViewMenuPills', () => {
  it('runs initial import-visibility sync on construction: design open, not assembly → import items hidden', () => {
    const els = mountChrome()
    const store = createMockStore({ currentDesign: { metadata: { name: 'x' } }, assemblyActive: false })
    initViewMenuPills({ store, setMenuToggle: vi.fn() })
    expect(els['menu-file-import-cadnano'].style.display).toBe('none')
    expect(els['menu-file-import-scadnano'].style.display).toBe('none')
  })

  it('initial sync: no design → import items shown', () => {
    const els = mountChrome()
    const store = createMockStore({ currentDesign: null, assemblyActive: false })
    initViewMenuPills({ store, setMenuToggle: vi.fn() })
    expect(els['menu-file-import-cadnano'].style.display).toBe('')
  })

  it('assemblyActive true → swaps Tools↔Assembly menus, hides single-design view toggles, re-syncs import', () => {
    const els = mountChrome()
    const store = createMockStore({ currentDesign: { metadata: {} }, assemblyActive: false })
    initViewMenuPills({ store, setMenuToggle: vi.fn() })
    store.setState({ assemblyActive: true })
    expect(els['menu-item-assembly'].style.display).toBe('')
    expect(els['menu-item-tools'].style.display).toBe('none')
    expect(els['menu-view-slice'].style.display).toBe('none')
    expect(els['menu-view-unfold'].style.display).toBe('none')
    expect(els['menu-view-cadnano'].style.display).toBe('none')
    // import re-syncs: assembly mode shows import even with a design open
    expect(els['menu-file-import-cadnano'].style.display).toBe('')
  })

  it('assemblyActive false → restores Tools menu + view toggles', () => {
    const els = mountChrome()
    const store = createMockStore({ assemblyActive: true })
    initViewMenuPills({ store, setMenuToggle: vi.fn() })
    store.setState({ assemblyActive: false })
    expect(els['menu-item-assembly'].style.display).toBe('none')
    expect(els['menu-item-tools'].style.display).toBe('')
    expect(els['menu-view-unfold'].style.display).toBe('')
  })

  it('currentDesign change re-syncs import visibility', () => {
    const els = mountChrome()
    const store = createMockStore({ currentDesign: null, assemblyActive: false })
    initViewMenuPills({ store, setMenuToggle: vi.fn() })
    expect(els['menu-file-import-cadnano'].style.display).toBe('')
    store.setState({ currentDesign: { metadata: {} } })
    expect(els['menu-file-import-cadnano'].style.display).toBe('none')
  })

  it('unfoldActive change pills the unfold menu + greys deform', () => {
    const els = mountChrome()
    const setMenuToggle = vi.fn()
    const store = createMockStore({ unfoldActive: false, cadnanoActive: false })
    initViewMenuPills({ store, setMenuToggle })
    store.setState({ unfoldActive: true })
    expect(setMenuToggle).toHaveBeenCalledWith('menu-view-unfold', true)
    expect(els['menu-view-deform'].classList.contains('disabled')).toBe(true)
  })

  it('cadnanoActive change pills the cadnano menu + greys deform', () => {
    const els = mountChrome()
    const setMenuToggle = vi.fn()
    const store = createMockStore({ unfoldActive: false, cadnanoActive: false })
    initViewMenuPills({ store, setMenuToggle })
    store.setState({ cadnanoActive: true })
    expect(setMenuToggle).toHaveBeenCalledWith('menu-view-cadnano', true)
    expect(els['menu-view-deform'].classList.contains('disabled')).toBe(true)
  })

  it('deform un-greys when both cadnano and unfold are off', () => {
    const els = mountChrome()
    const store = createMockStore({ cadnanoActive: true, unfoldActive: false })
    initViewMenuPills({ store, setMenuToggle: vi.fn() })
    store.setState({ cadnanoActive: false })
    expect(els['menu-view-deform'].classList.contains('disabled')).toBe(false)
  })

  it('store-backed pill toggles call setMenuToggle with the right id+value', () => {
    mountChrome()
    const setMenuToggle = vi.fn()
    const store = createMockStore({})
    initViewMenuPills({ store, setMenuToggle })
    store.setState({ deformVisuActive: true })
    store.setState({ showHelixLabels: true })
    store.setState({ showSequences: true })
    store.setState({ staplesHidden: true })
    expect(setMenuToggle).toHaveBeenCalledWith('menu-view-deform', true)
    expect(setMenuToggle).toHaveBeenCalledWith('menu-view-helix-labels', true)
    expect(setMenuToggle).toHaveBeenCalledWith('menu-view-sequences', true)
    expect(setMenuToggle).toHaveBeenCalledWith('menu-view-hide-staples', true)
  })

  it('unfold deactivating while cadnano inactive resets the mode indicator', () => {
    const els = mountChrome()
    els['mode-indicator'].textContent = 'NADOC · UNFOLD'
    const store = createMockStore({ unfoldActive: true, cadnanoActive: false })
    initViewMenuPills({ store, setMenuToggle: vi.fn() })
    store.setState({ unfoldActive: false })
    expect(els['mode-indicator'].textContent).toBe('NADOC · WORKSPACE')
  })

  it('no spurious calls when an unrelated field changes', () => {
    mountChrome()
    const setMenuToggle = vi.fn()
    const store = createMockStore({ unfoldActive: false })
    initViewMenuPills({ store, setMenuToggle })
    store.setState({ somethingElse: 1 })
    expect(setMenuToggle).not.toHaveBeenCalled()
  })
})
