/**
 * Tests for the Autoscaffold picker (autoscaffold_picker.js).
 *
 *   autoscaffoldModeConfig — pure (radio value → progress copy + api method + fail label).
 *   initAutoscaffoldPicker  — factory wiring: menu opens modal, Run dispatches the
 *                             picked mode's api call, success ticks the routing check,
 *                             failure toasts, Cancel / backdrop close the modal.
 *
 * showToast + op_progress are mocked so dispatch is assertable without real DOM widgets.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
import { showToast } from './toast.js'

vi.mock('./op_progress.js', () => ({ showOpProgress: vi.fn(), hideOpProgress: vi.fn() }))
import { showOpProgress, hideOpProgress } from './op_progress.js'

import {
  AUTOSCAFFOLD_MODES,
  autoscaffoldModeConfig,
  initAutoscaffoldPicker,
} from './autoscaffold_picker.js'

const tick = () => new Promise(r => setTimeout(r, 0))

// ── autoscaffoldModeConfig (pure) ────────────────────────────────────────────

describe('autoscaffoldModeConfig', () => {
  it('maps each known mode to its own config object', () => {
    expect(autoscaffoldModeConfig('seamless').apiMethod).toBe('autoScaffoldSeamless')
    expect(autoscaffoldModeConfig('matched').apiMethod).toBe('autoScaffoldMatched')
    expect(autoscaffoldModeConfig('advanced-seamed').apiMethod).toBe('autoScaffoldAdvancedSeamed')
    expect(autoscaffoldModeConfig('advanced-seamless').apiMethod).toBe('autoScaffoldAdvancedSeamless')
    expect(autoscaffoldModeConfig('seamed').apiMethod).toBe('autoScaffoldSeamed')
  })
  it('falls back to the seamed config for an unknown mode (the original else branch)', () => {
    expect(autoscaffoldModeConfig('bogus')).toBe(AUTOSCAFFOLD_MODES.seamed)
    expect(autoscaffoldModeConfig(undefined)).toBe(AUTOSCAFFOLD_MODES.seamed)
  })
  it('carries the verbatim fail labels', () => {
    expect(autoscaffoldModeConfig('seamless').failLabel).toBe('Seamless scaffold failed')
    expect(autoscaffoldModeConfig('matched').failLabel).toBe('Matched-ends scaffold failed')
    expect(autoscaffoldModeConfig('advanced-seamed').failLabel).toBe('Advanced seam routing failed')
    expect(autoscaffoldModeConfig('advanced-seamless').failLabel).toBe('Advanced seamless routing failed')
    expect(autoscaffoldModeConfig('seamed').failLabel).toBe('Seamed autoscaffold failed')
  })
})

// ── initAutoscaffoldPicker (factory) ─────────────────────────────────────────

function mountPicker(mode = 'seamed') {
  const els = mountIds({
    'autoscaffold-modal': 'div',
    'as-run': 'button',
    'as-cancel': 'button',
    'menu-routing-scaffold-ends': 'button',
  })
  // one checked radio inside the modal
  const radio = document.createElement('input')
  radio.type = 'radio'
  radio.name = 'as-mode'
  radio.value = mode
  radio.checked = true
  els['autoscaffold-modal'].appendChild(radio)
  return els
}

describe('initAutoscaffoldPicker', () => {
  beforeEach(() => { clearDom(); vi.clearAllMocks() })

  it('does not throw when its DOM is absent', () => {
    clearDom()
    const store = createMockStore({ currentDesign: {} })
    expect(() => initAutoscaffoldPicker({ store, api: {}, setRoutingCheck: vi.fn() })).not.toThrow()
  })

  it('menu click opens the modal only when a design is loaded', () => {
    const els = mountPicker()
    const store = createMockStore({ currentDesign: null })
    initAutoscaffoldPicker({ store, api: {}, setRoutingCheck: vi.fn() })

    els['menu-routing-scaffold-ends'].click()
    expect(els['autoscaffold-modal'].classList.contains('visible')).toBe(false)
    expect(showToast).toHaveBeenCalledWith('No design loaded.', { severity: 'error' })

    store.setState({ currentDesign: {} })
    els['menu-routing-scaffold-ends'].click()
    expect(els['autoscaffold-modal'].classList.contains('visible')).toBe(true)
  })

  it('Run with no design guards + toasts, no api call', async () => {
    const els = mountPicker()
    const api = { autoScaffoldSeamed: vi.fn() }
    const store = createMockStore({ currentDesign: null })
    initAutoscaffoldPicker({ store, api, setRoutingCheck: vi.fn() })

    els['as-run'].click()
    await tick()
    expect(api.autoScaffoldSeamed).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith('No design loaded.', { severity: 'error' })
  })

  it('Run dispatches the picked mode + shows/hides progress + ticks the routing check on success', async () => {
    const els = mountPicker('advanced-seamless')
    els['autoscaffold-modal'].classList.add('visible')
    const api = { autoScaffoldAdvancedSeamless: vi.fn().mockResolvedValue(true) }
    const setRoutingCheck = vi.fn()
    const store = createMockStore({ currentDesign: {} })
    initAutoscaffoldPicker({ store, api, setRoutingCheck })

    els['as-run'].click()
    await tick()
    expect(els['autoscaffold-modal'].classList.contains('visible')).toBe(false)
    expect(showOpProgress).toHaveBeenCalledWith('Advanced Seamless Routing', 'Routing scaffold with experimental seamless planner…')
    expect(api.autoScaffoldAdvancedSeamless).toHaveBeenCalledTimes(1)
    expect(hideOpProgress).toHaveBeenCalledTimes(1)
    expect(setRoutingCheck).toHaveBeenCalledWith('scaffoldEnds', true)
  })

  it('Run defaults to the seamed api when no radio is checked', async () => {
    const els = mountIds({
      'autoscaffold-modal': 'div', 'as-run': 'button',
      'as-cancel': 'button', 'menu-routing-scaffold-ends': 'button',
    })
    const api = { autoScaffoldSeamed: vi.fn().mockResolvedValue(true) }
    const setRoutingCheck = vi.fn()
    const store = createMockStore({ currentDesign: {} })
    initAutoscaffoldPicker({ store, api, setRoutingCheck })

    els['as-run'].click()
    await tick()
    expect(api.autoScaffoldSeamed).toHaveBeenCalledTimes(1)
    expect(setRoutingCheck).toHaveBeenCalledWith('scaffoldEnds', true)
  })

  it('Run failure toasts the fail label + backend error, no routing check', async () => {
    const els = mountPicker('seamless')
    const api = { autoScaffoldSeamless: vi.fn().mockResolvedValue(false) }
    const setRoutingCheck = vi.fn()
    const store = createMockStore({ currentDesign: {}, lastError: { message: 'no contiguous path' } })
    initAutoscaffoldPicker({ store, api, setRoutingCheck })

    els['as-run'].click()
    await tick()
    expect(showToast).toHaveBeenCalledWith('Seamless scaffold failed: no contiguous path', { severity: 'error' })
    expect(setRoutingCheck).not.toHaveBeenCalled()
  })

  it('Cancel and backdrop click both close the modal', () => {
    const els = mountPicker()
    els['autoscaffold-modal'].classList.add('visible')
    const store = createMockStore({ currentDesign: {} })
    initAutoscaffoldPicker({ store, api: {}, setRoutingCheck: vi.fn() })

    els['as-cancel'].click()
    expect(els['autoscaffold-modal'].classList.contains('visible')).toBe(false)

    els['autoscaffold-modal'].classList.add('visible')
    els['autoscaffold-modal'].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    // target === modal → closes
    expect(els['autoscaffold-modal'].classList.contains('visible')).toBe(false)
  })
})
