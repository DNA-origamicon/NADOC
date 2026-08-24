/**
 * Tests for the File → Export submenu (export_menu.js).
 *
 *   exportErrorMessage — pure (plain state → message string).
 *   showPdbPositionModal — DOM builder (jsdom).
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
import { showToast, showPersistentToast, dismissToast } from './toast.js'

import {
  exportErrorMessage,
  showPdbPositionModal,
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

describe('showPdbPositionModal', () => {
  beforeEach(() => { clearDom() })

  it('names the active visualization and resolves the selected positions', async () => {
    const result = showPdbPositionModal('oxDNA RMSF')
    expect(document.body.textContent).toContain('oxDNA RMSF is currently displayed')
    const button = [...document.querySelectorAll('button')].find(b => b.textContent === 'oxDNA RMSF positions')
    button.click()
    await expect(result).resolves.toBe('visualized')
  })

  it('identifies the exact current trajectory frame', async () => {
    const result = showPdbPositionModal('oxDNA trajectory', { frame: 17, total: 80 })
    expect(document.body.textContent).toContain('Export frame 17 of 80 from the oxDNA trajectory view?')
    const button = [...document.querySelectorAll('button')].find(b => b.textContent === 'Export frame 17 of 80')
    button.click()
    await expect(result).resolves.toBe('visualized')
  })

  it('offers current coloring enabled by default and returns the toggle state', async () => {
    const result = showPdbPositionModal('oxDNA RMSF', null, { title: 'RMSF', values: [{ value: 0.2 }] })
    const checkbox = document.querySelector('input[type="checkbox"]')
    expect(checkbox.checked).toBe(true)
    expect(document.body.textContent).toContain('Include current RMSF coloring')
    const button = [...document.querySelectorAll('button')].find(b => b.textContent === 'oxDNA RMSF positions')
    button.click()
    await expect(result).resolves.toEqual({ choice: 'visualized', includeColoring: true })
  })
})

// ── initExportMenu (factory) ─────────────────────────────────────────────────

const DOM = {
  'menu-file-export-seq-csv': 'div',
  'menu-file-export-seq-xlsx': 'div',
  'menu-file-export-idt-xlsx': 'div',
  'menu-file-export-cadnano': 'div',
  'menu-file-export-scadnano': 'div',
  'menu-file-export-pdb': 'div',
  'menu-file-export-psf': 'div',
  'menu-file-export-stl': 'div',
  'menu-file-export-3mf': 'div',
}

function makeDeps(initialState = {}) {
  const store = createMockStore(initialState)
  const api = {
    exportSequenceCsv: vi.fn().mockResolvedValue(true),
    exportSequenceXlsx: vi.fn().mockResolvedValue(true),
    exportIdtOrderXlsx: vi.fn().mockResolvedValue(true),
    exportCadnano: vi.fn().mockResolvedValue(true),
    exportScadnano: vi.fn().mockResolvedValue(true),
    exportSurfaceStl: vi.fn().mockResolvedValue(true),
    exportSurface3mf: vi.fn().mockResolvedValue({ ok: true }),
    exportPdb: vi.fn().mockResolvedValue(true),
    exportPsf: vi.fn().mockResolvedValue(true),
  }
  return { store, api }
}

const click = id => document.getElementById(id).dispatchEvent(new MouseEvent('click'))

describe('initExportMenu', () => {
  beforeEach(() => { clearDom(); vi.clearAllMocks() })

  it('returns its api and no-ops gracefully when the menu DOM is absent', () => {
    const out = initExportMenu(makeDeps())
    expect(out).toEqual({})
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

  it('scadnano export calls api.exportScadnano', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { strands: [] } })
    initExportMenu(deps)
    click('menu-file-export-scadnano')
    await tick()
    expect(deps.api.exportScadnano).toHaveBeenCalledTimes(1)
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

  it('IDT export forwards group and overhang-derived strand names', async () => {
    mountIds(DOM)
    const deps = makeDeps({
      currentDesign: {
        strands: [
          { id: 'body-1', strand_type: 'staple' },
          { id: 'body-2', strand_type: 'staple' },
          { id: 'tag', strand_type: 'staple' },
        ],
        overhangs: [{ id: 'oh-tag', strand_id: 'tag', label: 'Handle' }],
      },
      strandGroups: [{ name: 'Body', strandIds: ['body-1', 'body-2', 'tag'] }],
    })
    initExportMenu(deps)
    click('menu-file-export-idt-xlsx')
    await tick()
    expect(deps.api.exportIdtOrderXlsx).toHaveBeenCalledWith({
      'body-1': 'Body_1', 'body-2': 'Body_2', tag: 'Handle_1',
    })
  })

  it('PDB / PSF export call the doc-scoped api download methods', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { strands: [] } })
    initExportMenu(deps)
    click('menu-file-export-pdb')
    click('menu-file-export-psf')
    await tick()
    expect(deps.api.exportPdb).toHaveBeenCalledTimes(1)
    expect(showPersistentToast).toHaveBeenCalledWith('Generating PDB…', { severity: 'info', loading: true })
    expect(dismissToast).toHaveBeenCalledTimes(1)
    expect(showToast).toHaveBeenCalledWith('PDB generated. Download starting…', { severity: 'success' })
    expect(deps.api.exportPsf).toHaveBeenCalledTimes(1)
  })

  it('a failed PDB export toasts the backend error instead of downloading it', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { strands: [] }, lastError: { message: 'No active design.' } })
    deps.api.exportPdb.mockResolvedValue(false)
    initExportMenu(deps)
    click('menu-file-export-pdb')
    await tick()
    expect(showToast).toHaveBeenCalledWith('PDB export failed: No active design.', { severity: 'error' })
  })

  it('offers active simulation positions and forwards them when selected', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { strands: [] } })
    const positions = [{ helix_id: 'h0', bp_index: 1, direction: 'forward', backbone_position: [1, 2, 3] }]
    initExportMenu({ ...deps, getPdbVisualization: () => ({ name: 'oxDNA RMSF', positions }) })
    click('menu-file-export-pdb')
    await tick()
    ;[...document.querySelectorAll('button')].find(b => b.textContent === 'oxDNA RMSF positions').click()
    await tick()
    expect(deps.api.exportPdb).toHaveBeenCalledWith(positions, { name: 'oxDNA RMSF', positions })
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

})
