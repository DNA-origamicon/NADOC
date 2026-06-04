/**
 * Tests for the File → Export submenu (export_menu.js).
 *
 *   exportErrorMessage — pure (plain state → message string).
 *   triggerDownload / showNamdPromptModal — DOM builders (jsdom).
 *   initExportMenu — factory wiring: each menu click → api call / download /
 *                    toast, plus the "no design loaded" guard.
 *
 * showToast is mocked so message text is assertable; api is a vi.fn() bag.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

vi.mock('./toast.js', () => ({
  showToast: vi.fn(),
  showPersistentToast: vi.fn(),
  dismissToast: vi.fn(),
}))
import { showToast } from './toast.js'

import {
  exportErrorMessage,
  triggerDownload,
  showNamdPromptModal,
  initExportMenu,
} from './export_menu.js'

const tick = () => new Promise(r => setTimeout(r, 0))

// ── exportErrorMessage (pure) ────────────────────────────────────────────────

describe('exportErrorMessage', () => {
  it('returns the backend error message', () => {
    expect(exportErrorMessage({ lastError: { message: 'boom' } })).toBe('boom')
  })
  it("falls back to 'unknown' when there is no error / no state", () => {
    expect(exportErrorMessage({})).toBe('unknown')
    expect(exportErrorMessage({ lastError: {} })).toBe('unknown')
    expect(exportErrorMessage(null)).toBe('unknown')
    expect(exportErrorMessage(undefined)).toBe('unknown')
  })
})

// ── triggerDownload (DOM) ────────────────────────────────────────────────────

describe('triggerDownload', () => {
  it('creates a transient <a>, points it at the url, and clicks it', () => {
    const real = document.createElement.bind(document)
    const made = []
    const spy = vi.spyOn(document, 'createElement').mockImplementation(tag => {
      const el = real(tag)
      if (tag === 'a') { el.click = vi.fn(); made.push(el) }
      return el
    })
    triggerDownload('/api/design/export/pdb')
    expect(made).toHaveLength(1)
    expect(made[0].getAttribute('href')).toBe('/api/design/export/pdb')
    expect(made[0].download).toBe('')
    expect(made[0].click).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })
})

// ── showNamdPromptModal (DOM) ────────────────────────────────────────────────

describe('showNamdPromptModal', () => {
  beforeEach(() => { clearDom() })

  it('mounts an overlay prefilled with the prompt text', () => {
    showNamdPromptModal('STEP 1: do the thing')
    const ta = document.querySelector('textarea')
    expect(ta).toBeTruthy()
    expect(ta.value).toBe('STEP 1: do the thing')
    expect(ta.readOnly).toBe(true)
    expect(document.body.textContent).toContain('AI Assistant Prompt')
  })

  it('the returned cleanup removes the overlay; Close button also closes it', () => {
    const cleanup = showNamdPromptModal('x')
    expect(document.querySelector('textarea')).toBeTruthy()
    cleanup()
    expect(document.querySelector('textarea')).toBeNull()

    // and via the Close button
    showNamdPromptModal('y')
    const closeBtn = [...document.querySelectorAll('button')].find(b => b.textContent === 'Close')
    closeBtn.click()
    expect(document.querySelector('textarea')).toBeNull()
  })
})

// ── initExportMenu (factory) ─────────────────────────────────────────────────

const DOM = {
  'menu-file-export-seq-csv': 'div',
  'menu-file-export-seq-xlsx': 'div',
  'menu-file-export-cadnano': 'div',
  'menu-file-export-pdb': 'div',
  'menu-file-export-psf': 'div',
  'menu-file-export-stl': 'div',
  'menu-file-export-3mf': 'div',
  'menu-file-export-namd-complete': 'div',
  'gromacs-job-toast': 'div',
  'gromacs-job-label': 'div',
  'gromacs-job-download': 'div',
  'gromacs-job-dismiss': 'div',
  'menu-file-export-gromacs-complete': 'div',
}

function makeDeps(initialState = {}) {
  const store = createMockStore(initialState)
  const api = {
    exportSequenceCsv: vi.fn().mockResolvedValue(true),
    exportSequenceXlsx: vi.fn().mockResolvedValue(true),
    exportCadnano: vi.fn().mockResolvedValue(true),
    exportSurfaceStl: vi.fn().mockResolvedValue(true),
    exportSurface3mf: vi.fn().mockResolvedValue({ ok: true }),
  }
  return { store, api }
}

const click = id => document.getElementById(id).dispatchEvent(new MouseEvent('click'))

describe('initExportMenu', () => {
  beforeEach(() => { clearDom(); vi.clearAllMocks() })

  it('returns its api and no-ops gracefully when the menu DOM is absent', () => {
    const out = initExportMenu(makeDeps())
    expect(out.showNamdPromptModal).toBe(showNamdPromptModal)
  })

  it('CSV export calls api.exportSequenceCsv when a design is loaded', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { strands: [] } })
    initExportMenu(deps)
    click('menu-file-export-seq-csv')
    await tick()
    expect(deps.api.exportSequenceCsv).toHaveBeenCalledTimes(1)
    expect(showToast).not.toHaveBeenCalled()
  })

  it('CSV export with no design loaded toasts and never calls the api', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: null })
    initExportMenu(deps)
    click('menu-file-export-seq-csv')
    await tick()
    expect(deps.api.exportSequenceCsv).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith('No design loaded.', { severity: 'error' })
  })

  it('a failed export surfaces the backend error message', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { strands: [] }, lastError: { message: 'disk full' } })
    deps.api.exportSequenceCsv.mockResolvedValue(false)
    initExportMenu(deps)
    click('menu-file-export-seq-csv')
    await tick()
    expect(showToast).toHaveBeenCalledWith('Export failed: disk full', { severity: 'error' })
  })

  it('Excel export forwards the staple color order to the api', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { strands: [] } })
    initExportMenu(deps)
    click('menu-file-export-seq-xlsx')
    await tick()
    expect(deps.api.exportSequenceXlsx).toHaveBeenCalledWith({}, [])
  })

  it('PDB / PSF export trigger direct downloads of the backend URLs', () => {
    mountIds(DOM)
    const real = document.createElement.bind(document)
    const made = []
    const spy = vi.spyOn(document, 'createElement').mockImplementation(tag => {
      const el = real(tag)
      if (tag === 'a') { el.click = vi.fn(); made.push(el) }
      return el
    })
    const deps = makeDeps({ currentDesign: { strands: [] } })
    initExportMenu(deps)
    click('menu-file-export-pdb')
    click('menu-file-export-psf')
    expect(made.map(a => a.getAttribute('href'))).toEqual([
      '/api/design/export/pdb',
      '/api/design/export/psf',
    ])
    expect(made.every(a => a.click.mock.calls.length === 1)).toBe(true)
    spy.mockRestore()
  })

  it('STL export reports success', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { strands: [] } })
    initExportMenu(deps)
    click('menu-file-export-stl')
    await tick()
    expect(showToast).toHaveBeenCalledWith('Building surface STL…', { severity: 'info' })
    expect(showToast).toHaveBeenCalledWith('Surface STL exported (auto-scaled to 200 mm).', { severity: 'success' })
  })

  it('3MF export appends the coloring detail on success', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { strands: [] } })
    deps.api.exportSurface3mf.mockResolvedValue({ ok: true, coloring: 'by group' })
    initExportMenu(deps)
    click('menu-file-export-3mf')
    await tick()
    expect(showToast).toHaveBeenCalledWith(
      'Surface 3MF exported: scaffold + 3 staple colors, 200 mm (by group).',
      { severity: 'success' },
    )
  })

  it('GROMACS export is stubbed — shows the "being re-worked" toast', () => {
    mountIds(DOM)
    initExportMenu(makeDeps({ currentDesign: { strands: [] } }))
    click('menu-file-export-gromacs-complete')
    expect(showToast).toHaveBeenCalledWith(
      'GROMACS export is being re-worked — try again after the next deploy.',
      { severity: 'error' },
    )
  })

  it('GROMACS job-toast dismiss clears the toast class', () => {
    mountIds(DOM)
    const toastEl = document.getElementById('gromacs-job-toast')
    toastEl.className = 'show'
    initExportMenu(makeDeps())
    click('gromacs-job-dismiss')
    expect(toastEl.className).toBe('')
  })

  it('NAMD package export downloads then shows the prompt modal', async () => {
    mountIds(DOM)
    const real = document.createElement.bind(document)
    const made = []
    const spy = vi.spyOn(document, 'createElement').mockImplementation(tag => {
      const el = real(tag)
      if (tag === 'a') { el.click = vi.fn(); made.push(el) }
      return el
    })
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      text: async () => 'PROMPT BODY',
    })
    const deps = makeDeps({ currentDesign: { strands: [] } })
    initExportMenu(deps)
    click('menu-file-export-namd-complete')
    await tick()
    await tick()
    expect(made.some(a => a.getAttribute('href') === '/api/design/export/namd-complete')).toBe(true)
    expect(fetchSpy).toHaveBeenCalledWith('/api/design/export/namd-prompt', expect.any(Object))
    const ta = document.querySelector('textarea')
    expect(ta?.value).toBe('PROMPT BODY')
    spy.mockRestore()
    fetchSpy.mockRestore()
  })
})
