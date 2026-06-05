/**
 * Tests for the Autobreak modal (autobreak_modal.js).
 *
 *   readAkselOptions   — pure (raw input strings → clamped backend options object).
 *   initAutobreakModal — factory wiring: menu opens the modal (guarded on a loaded
 *                        design), Score/Preview/Run dispatch the right api call with
 *                        the read options, success/failure drive report + toast.
 *
 * toast + op_progress are mocked so dispatch is assertable; createModal/createButton
 * and aksel_format are real (pure, jsdom-friendly).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { clearDom } from '../test-helpers/factory_dom.js'

vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
import { showToast } from './toast.js'

vi.mock('./op_progress.js', () => ({ showOpProgress: vi.fn(), hideOpProgress: vi.fn() }))
import { showOpProgress, hideOpProgress } from './op_progress.js'

import { readAkselOptions, initAutobreakModal } from './autobreak_modal.js'

const tick = () => new Promise(r => setTimeout(r, 0))

// ── readAkselOptions (pure) ──────────────────────────────────────────────────

describe('readAkselOptions', () => {
  it('returns the verbatim defaults when every input is absent', () => {
    expect(readAkselOptions()).toEqual({
      min_staple_nt: 21, max_staple_nt: 60, k_paths: 3, path_index: 0,
    })
  })
  it('parses valid numeric strings', () => {
    expect(readAkselOptions({ minNt: '18', maxNt: '49', kPaths: '5', pathIndex: '2' })).toEqual({
      min_staple_nt: 18, max_staple_nt: 49, k_paths: 5, path_index: 2,
    })
  })
  it('falls back to defaults for empty / non-numeric values', () => {
    expect(readAkselOptions({ minNt: '', maxNt: 'abc', kPaths: undefined, pathIndex: '' })).toEqual({
      min_staple_nt: 21, max_staple_nt: 60, k_paths: 3, path_index: 0,
    })
  })
  it('clamps each field independently (mixed valid/invalid)', () => {
    expect(readAkselOptions({ minNt: '30', maxNt: 'x', kPaths: '7', pathIndex: 'y' })).toEqual({
      min_staple_nt: 30, max_staple_nt: 60, k_paths: 7, path_index: 0,
    })
  })
})

// ── initAutobreakModal (factory) ─────────────────────────────────────────────

function mountAutobreakDom({ algo = 'basic', minNt = '21' } = {}) {
  // Modal body markup mirroring index.html#autobreak-modal-body.
  const body = document.createElement('div')
  body.id = 'autobreak-modal-body'
  body.setAttribute('hidden', '')
  body.innerHTML = `
    <input type="radio" name="ab-algo" value="basic">
    <input type="radio" name="ab-algo" value="aksel">
    <input type="radio" name="ab-algo" value="advanced">
    <input id="ab-min-nt" value="${minNt}">
    <input id="ab-max-nt" value="60">
    <input id="ab-k-paths" value="3">
    <input id="ab-path-index" value="0">
    <div id="ab-aksel-report"></div>
  `
  body.querySelector(`input[name="ab-algo"][value="${algo}"]`).checked = true
  document.body.appendChild(body)

  const menuBtn = document.createElement('button')
  menuBtn.id = 'menu-routing-autobreak'
  document.body.appendChild(menuBtn)

  const fill = document.createElement('div')
  fill.id = 'op-progress-fill'
  document.body.appendChild(fill)

  return { body, menuBtn, fill }
}

// Click a modal action button by its label text.
function clickAction(label) {
  const btn = [...document.querySelectorAll('.modal__actions button')]
    .find(b => b.textContent.trim() === label)
  expect(btn, `action button "${label}"`).toBeTruthy()
  btn.click()
}

describe('initAutobreakModal', () => {
  beforeEach(() => { clearDom(); vi.clearAllMocks() })

  it('does not throw when its menu button is absent', () => {
    const store = createMockStore({ currentDesign: { helices: [{}] } })
    expect(() => initAutobreakModal({ store, api: {} })).not.toThrow()
  })

  it('menu click guards on a loaded design (no helices → toast, no modal built)', () => {
    mountAutobreakDom()
    const store = createMockStore({ currentDesign: { helices: [] } })
    initAutobreakModal({ store, api: {} })

    document.getElementById('menu-routing-autobreak').click()
    expect(showToast).toHaveBeenCalledWith('No design loaded.', { severity: 'error' })
    expect(document.querySelector('.modal__actions')).toBeNull()
  })

  it('menu click with a loaded design builds + opens the modal once', () => {
    mountAutobreakDom()
    const store = createMockStore({ currentDesign: { helices: [{}] } })
    initAutobreakModal({ store, api: {} })

    const menuBtn = document.getElementById('menu-routing-autobreak')
    menuBtn.click()
    expect(document.querySelectorAll('.modal__overlay').length).toBe(1)
    // Re-open: _buildOnce is idempotent (no second modal built).
    menuBtn.click()
    expect(document.querySelectorAll('.modal__overlay').length).toBe(1)
  })

  it('Score dispatches scoreStaples with the read options and shows the report', async () => {
    mountAutobreakDom({ minNt: '18' })
    const api = { scoreStaples: vi.fn().mockResolvedValue({ ok: true }) }
    const store = createMockStore({ currentDesign: { helices: [{}] } })
    initAutobreakModal({ store, api })

    document.getElementById('menu-routing-autobreak').click()
    clickAction('Score')
    await tick()
    expect(api.scoreStaples).toHaveBeenCalledWith(
      { min_staple_nt: 18, max_staple_nt: 60, k_paths: 3, path_index: 0 },
    )
    const report = document.getElementById('ab-aksel-report')
    expect(report.style.display).toBe('block')
    expect(report.textContent).toContain('Current route')
  })

  it('Score failure renders an error report', async () => {
    mountAutobreakDom()
    const api = { scoreStaples: vi.fn().mockResolvedValue(null) }
    const store = createMockStore({ currentDesign: { helices: [{}] }, lastError: { message: 'no staples' } })
    initAutobreakModal({ store, api })

    document.getElementById('menu-routing-autobreak').click()
    clickAction('Score')
    await tick()
    const report = document.getElementById('ab-aksel-report')
    expect(report.textContent).toContain('Score failed: no staples')
  })

  it('Preview shows/hides op-progress and dispatches buildStaplePrecursorGraphs', async () => {
    mountAutobreakDom()
    const api = { buildStaplePrecursorGraphs: vi.fn().mockResolvedValue({ ok: true }) }
    const store = createMockStore({ currentDesign: { helices: [{}] } })
    initAutobreakModal({ store, api })

    document.getElementById('menu-routing-autobreak').click()
    clickAction('Preview')
    await tick()
    expect(showOpProgress).toHaveBeenCalledWith('Aksel preview', 'Scoring candidate breaks…')
    expect(api.buildStaplePrecursorGraphs).toHaveBeenCalledTimes(1)
    expect(hideOpProgress).toHaveBeenCalledTimes(1)
  })

  it('Run with the basic algorithm calls addAutoBreak and closes the modal', async () => {
    mountAutobreakDom({ algo: 'basic' })
    const api = { addAutoBreak: vi.fn().mockResolvedValue({}) }
    const store = createMockStore({ currentDesign: { helices: [{}] } })
    initAutobreakModal({ store, api })

    document.getElementById('menu-routing-autobreak').click()
    clickAction('Run Autobreak')
    await tick()
    expect(api.addAutoBreak).toHaveBeenCalledWith({ algorithm: 'basic' })
    expect(showToast).toHaveBeenCalledWith('Autobreak complete.')
    expect(document.querySelector('.modal__overlay')).toBeNull()  // closed
  })

  it('Run with the aksel algorithm dispatches addAutoRouteAksel with options + aksel toast', async () => {
    mountAutobreakDom({ algo: 'aksel' })
    const api = {
      addAutoRouteAksel: vi.fn().mockResolvedValue({
        aksel_route: { aksel_break: { new_staple_count: 42, length_violation_count: 1 }, auto_crossover: { placed: 7 } },
      }),
    }
    const store = createMockStore({ currentDesign: { helices: [{}] } })
    initAutobreakModal({ store, api })

    document.getElementById('menu-routing-autobreak').click()
    clickAction('Run Autobreak')
    await tick()
    expect(api.addAutoRouteAksel).toHaveBeenCalledWith(
      { min_staple_nt: 21, max_staple_nt: 60, k_paths: 3, path_index: 0 },
    )
    expect(showToast).toHaveBeenCalledWith('Aksel route (7 crossovers) complete: 42 staples, 1 length violations.')
  })

  it('Run failure toasts the backend error', async () => {
    mountAutobreakDom({ algo: 'basic' })
    const api = { addAutoBreak: vi.fn().mockResolvedValue(null) }
    const store = createMockStore({ currentDesign: { helices: [{}] }, lastError: { message: 'route blocked' } })
    initAutobreakModal({ store, api })

    document.getElementById('menu-routing-autobreak').click()
    clickAction('Run Autobreak')
    await tick()
    expect(showToast).toHaveBeenCalledWith('Autobreak failed: route blocked', { severity: 'error' })
  })
})
