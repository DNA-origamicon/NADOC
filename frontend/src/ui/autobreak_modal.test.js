/**
 * Tests for the Autobreak modal (autobreak_modal.js).
 *
 *   initAutobreakModal — factory wiring: menu opens the modal (guarded on a loaded
 *                        design), Run dispatches addAutoBreak, success/failure drive
 *                        the toast. (The Aksel optimizer + Score/Preview were removed.)
 *
 * toast + op_progress are mocked so dispatch is assertable; createModal/createButton
 * are real (pure, jsdom-friendly).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { clearDom } from '../test-helpers/factory_dom.js'

vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
import { showToast } from './toast.js'

vi.mock('./op_progress.js', () => ({ showOpProgress: vi.fn(), hideOpProgress: vi.fn() }))
import { showOpProgress, hideOpProgress } from './op_progress.js'

import { initAutobreakModal } from './autobreak_modal.js'

const tick = () => new Promise(r => setTimeout(r, 0))

// ── initAutobreakModal (factory) ─────────────────────────────────────────────

function mountAutobreakDom() {
  // Modal body markup mirroring index.html#autobreak-modal-body.
  const body = document.createElement('div')
  body.id = 'autobreak-modal-body'
  body.setAttribute('hidden', '')
  document.body.appendChild(body)

  const menuBtn = document.createElement('button')
  menuBtn.id = 'menu-routing-autobreak'
  document.body.appendChild(menuBtn)

  return { body, menuBtn }
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

  it('Run dispatches addAutoBreak, shows op-progress, and closes the modal', async () => {
    mountAutobreakDom()
    const api = { addAutoBreak: vi.fn().mockResolvedValue({}) }
    const store = createMockStore({ currentDesign: { helices: [{}] } })
    initAutobreakModal({ store, api })

    document.getElementById('menu-routing-autobreak').click()
    clickAction('Run Autobreak')
    await tick()
    expect(api.addAutoBreak).toHaveBeenCalledWith({})
    expect(showOpProgress).toHaveBeenCalledTimes(1)
    expect(hideOpProgress).toHaveBeenCalledTimes(1)
    expect(showToast).toHaveBeenCalledWith('Autobreak complete.')
    expect(document.querySelector('.modal__overlay')).toBeNull()  // closed
  })

  it('Run failure toasts the backend error', async () => {
    mountAutobreakDom()
    const api = { addAutoBreak: vi.fn().mockResolvedValue(null) }
    const store = createMockStore({ currentDesign: { helices: [{}] }, lastError: { message: 'route blocked' } })
    initAutobreakModal({ store, api })

    document.getElementById('menu-routing-autobreak').click()
    clickAction('Run Autobreak')
    await tick()
    expect(showToast).toHaveBeenCalledWith('Autobreak failed: route blocked', { severity: 'error' })
  })
})
