/**
 * Factory-wiring tests for the Extrude tool sidebar panel.
 *
 * jsdom DOM (#extrude-panel + #extrude-from + #mode-indicator) + a mock store and
 * mock slicePlane/expandedSpacing. Asserts the observable contract: panel
 * visibility, the dropdown state machine, the slicePlane calls, and clean teardown.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initExtrudePanel } from './extrude_panel.js'

function makeDeps(initialState = {}) {
  const store = createMockStore({ currentDesign: { lattice_type: 'HONEYCOMB', helices: [] }, ...initialState })
  const slicePlane = {
    show: vi.fn(),
    hide: vi.fn(),
    setExtrudeUiOpen: vi.fn(),
  }
  const expandedSpacing = { forceOff: vi.fn() }
  return { store, slicePlane, expandedSpacing }
}

beforeEach(() => {
  mountIds({ 'extrude-panel': 'div', 'extrude-from': 'select', 'mode-indicator': 'div' })
  // The dropdown needs its three real options so `.value =` sticks.
  const sel = document.getElementById('extrude-from')
  for (const v of ['XY', 'XZ', 'YZ']) {
    const o = document.createElement('option'); o.value = v; sel.appendChild(o)
  }
})

describe('initExtrudePanel — new-bundle', () => {
  it('activate("newBundle") shows the panel on the default plane and opens the slice UI', () => {
    const deps = makeDeps()
    const panel = initExtrudePanel(deps)
    panel.activate('newBundle')

    expect(deps.expandedSpacing.forceOff).toHaveBeenCalled()
    expect(document.getElementById('extrude-panel').style.display).toBe('block')
    expect(document.getElementById('extrude-from').disabled).toBe(false)
    expect(document.getElementById('extrude-from').value).toBe('XY')
    expect(deps.slicePlane.setExtrudeUiOpen).toHaveBeenCalledWith(true)
    expect(deps.slicePlane.show).toHaveBeenCalledWith(
      'XY', 0, false, false, { latticeType: 'HONEYCOMB', newBundle: true },
    )
    expect(deps.store.getState().currentPlane).toBe('XY')
    expect(panel.isActive()).toBe(true)
  })

  it('defaults to the design currentPlane when one is set', () => {
    const deps = makeDeps({ currentPlane: 'XZ' })
    const panel = initExtrudePanel(deps)
    panel.activate('newBundle')
    expect(document.getElementById('extrude-from').value).toBe('XZ')
    expect(deps.slicePlane.show).toHaveBeenCalledWith('XZ', 0, false, false, expect.objectContaining({ newBundle: true }))
  })

  it('changing the dropdown re-shows on the new origin plane and updates the store', () => {
    const deps = makeDeps()
    const panel = initExtrudePanel(deps)
    panel.activate('newBundle')
    deps.slicePlane.show.mockClear()

    const sel = document.getElementById('extrude-from')
    sel.value = 'YZ'
    sel.dispatchEvent(new Event('change'))

    expect(deps.store.getState().currentPlane).toBe('YZ')
    expect(deps.slicePlane.show).toHaveBeenCalledWith('YZ', 0, false, false, expect.objectContaining({ newBundle: true }))
  })
})

describe('initExtrudePanel — context modes', () => {
  it('activate("continuation") locks the dropdown to the context plane and does NOT call slicePlane.show', () => {
    const deps = makeDeps()
    const panel = initExtrudePanel(deps)
    panel.activate('continuation', { plane: 'YZ' })

    expect(document.getElementById('extrude-panel').style.display).toBe('block')
    expect(document.getElementById('extrude-from').value).toBe('YZ')
    expect(document.getElementById('extrude-from').disabled).toBe(true)
    expect(deps.slicePlane.setExtrudeUiOpen).toHaveBeenCalledWith(true)
    // The caller (blunt_end_menus) drives showAtEnd/showDeformed, not this module.
    expect(deps.slicePlane.show).not.toHaveBeenCalled()
  })

  it('a locked dropdown change is ignored (no re-show)', () => {
    const deps = makeDeps()
    const panel = initExtrudePanel(deps)
    panel.activate('continuation', { plane: 'XZ' })
    const sel = document.getElementById('extrude-from')
    sel.value = 'XY'
    sel.dispatchEvent(new Event('change'))
    expect(deps.slicePlane.show).not.toHaveBeenCalled()
  })
})

describe('initExtrudePanel — hide', () => {
  it('tears down panel + slice widget + indicator and re-enables the dropdown', () => {
    const deps = makeDeps()
    const panel = initExtrudePanel(deps)
    panel.activate('continuation', { plane: 'XZ' })
    panel.hide()

    expect(panel.isActive()).toBe(false)
    expect(document.getElementById('extrude-panel').style.display).toBe('none')
    expect(document.getElementById('extrude-from').disabled).toBe(false)
    expect(deps.slicePlane.setExtrudeUiOpen).toHaveBeenLastCalledWith(false)
    expect(deps.slicePlane.hide).toHaveBeenCalled()
    expect(document.getElementById('mode-indicator').textContent).toBe('NADOC · WORKSPACE')
  })

  it('re-activation works after hide (clean lifecycle)', () => {
    const deps = makeDeps()
    const panel = initExtrudePanel(deps)
    panel.activate('newBundle'); panel.hide(); panel.activate('newBundle')
    expect(panel.isActive()).toBe(true)
    expect(document.getElementById('extrude-panel').style.display).toBe('block')
  })
})
