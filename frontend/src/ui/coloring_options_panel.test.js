import { describe, it, expect, vi, beforeEach } from 'vitest'
import { initColoringOptionsPanel } from './coloring_options_panel.js'
import { COLORING_ORDER } from '../scene/coloring_modes.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

const BTN_IDS = COLORING_ORDER.map(m => [`repr-color-${m}`, 'button'])

function mountButtons() {
  return mountIds(Object.fromEntries(BTN_IDS))
}

describe('initColoringOptionsPanel', () => {
  beforeEach(clearDom)

  it('updateForRepr enables supported modes and disables the rest', () => {
    const els = mountButtons()
    const store = createMockStore({ assemblyActive: false, coloringMode: 'strand' })
    const panel = initColoringOptionsPanel({ store, onSelect: vi.fn() })

    panel.updateForRepr('cylinders')   // supports strand/cluster/overhang-only
    expect(els['repr-color-strand'].disabled).toBe(false)
    expect(els['repr-color-cluster'].disabled).toBe(false)
    expect(els['repr-color-overhang-only'].disabled).toBe(false)
    expect(els['repr-color-base'].disabled).toBe(true)
    expect(els['repr-color-cpk'].disabled).toBe(true)
    expect(els['repr-color-source'].disabled).toBe(true)
  })

  it('marks the current coloring mode active (when supported)', () => {
    const els = mountButtons()
    const store = createMockStore({ assemblyActive: false, coloringMode: 'cluster' })
    const panel = initColoringOptionsPanel({ store, onSelect: vi.fn() })

    panel.updateForRepr('full')
    expect(els['repr-color-cluster'].classList.contains('active')).toBe(true)
    expect(els['repr-color-strand'].classList.contains('active')).toBe(false)
  })

  it('clicking an enabled button calls onSelect; a disabled one does not', () => {
    const els = mountButtons()
    const onSelect = vi.fn()
    const store = createMockStore({ assemblyActive: false, coloringMode: 'strand' })
    const panel = initColoringOptionsPanel({ store, onSelect })

    panel.updateForRepr('full')        // base supported, source not
    els['repr-color-base'].click()
    expect(onSelect).toHaveBeenCalledWith('base')

    onSelect.mockClear()
    els['repr-color-source'].click()   // disabled → ignored
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('active highlight follows store.coloringMode changes from elsewhere', () => {
    const els = mountButtons()
    const store = createMockStore({ assemblyActive: false, coloringMode: 'strand' })
    const panel = initColoringOptionsPanel({ store, onSelect: vi.fn() })
    panel.updateForRepr('full')
    expect(els['repr-color-strand'].classList.contains('active')).toBe(true)

    store.setState({ coloringMode: 'base' })   // e.g. set from the View menu
    expect(els['repr-color-base'].classList.contains('active')).toBe(true)
    expect(els['repr-color-strand'].classList.contains('active')).toBe(false)
  })
})
