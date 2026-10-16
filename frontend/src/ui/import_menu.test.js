/**
 * Tests for the File → Import handlers (import_menu.js).
 *
 *   sanitizeImportName / importedClusterOverhangExtras — pure cores.
 *   runPdbImport — the file-input-free branch logic (null / needs-decision /
 *                  dna / protein / both), driven via a mock api + deps.
 *   initImportMenu — factory returns its callbacks + wires the PDB menu item.
 *
 * caDNAno/scadnano autodetection uses a controlled file-picker boundary to
 * exercise the actual import, atomic group omission, and save ordering.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

vi.mock('./toast.js', () => ({
  showToast: vi.fn(),
  showPersistentToast: vi.fn(),
  dismissToast: vi.fn(),
}))
vi.mock('./import_pdb_modal.js', () => ({ openImportPdbModal: vi.fn() }))
vi.mock('./file_browser.js', () => ({ openFileBrowser: vi.fn() }))

import { showToast } from './toast.js'
import { openImportPdbModal } from './import_pdb_modal.js'
import { openFileBrowser } from './file_browser.js'
import {
  sanitizeImportName,
  importedClusterOverhangExtras,
  initImportMenu,
} from './import_menu.js'

// ── sanitizeImportName (pure) ────────────────────────────────────────────────

describe('sanitizeImportName', () => {
  it('keeps the filename-safe charset (alnum, dash, underscore, space)', () => {
    expect(sanitizeImportName('My Design-2_v3')).toBe('My Design-2_v3')
  })
  it('replaces every other character with an underscore', () => {
    expect(sanitizeImportName('a/b.c:d')).toBe('a_b_c_d')
  })
  it('coerces null/undefined to an empty string', () => {
    expect(sanitizeImportName(null)).toBe('')
    expect(sanitizeImportName(undefined)).toBe('')
  })
})

// ── importedClusterOverhangExtras (pure) ─────────────────────────────────────

describe('importedClusterOverhangExtras', () => {
  it('returns non-default clusters and the overhangs array', () => {
    const design = {
      cluster_transforms: [{ id: 'a', is_default: true }, { id: 'b' }, { id: 'c', is_default: false }],
      overhangs: [{ id: 'o1' }],
    }
    const { clusters, overhangs } = importedClusterOverhangExtras(design)
    expect(clusters.map(c => c.id)).toEqual(['b', 'c'])
    expect(overhangs).toHaveLength(1)
  })
  it('defaults to empty arrays for a bare/empty design', () => {
    expect(importedClusterOverhangExtras(null)).toEqual({ clusters: [], overhangs: [] })
    expect(importedClusterOverhangExtras({})).toEqual({ clusters: [], overhangs: [] })
  })
})

// ── initImportMenu / runPdbImport (factory) ──────────────────────────────────

function makeDeps(initialState = {}, apiOverrides = {}) {
  const store = createMockStore(initialState)
  const api = {
    importCadnanoDesign: vi.fn(),
    importScadnanoDesign: vi.fn(),
    importPdbAuto: vi.fn(),
    syncDesignResponse: vi.fn(),
    saveDesignAs: vi.fn(),
    addInstance: vi.fn(),
    addRecentFile: vi.fn(),
    deleteCluster: vi.fn(),
    dissolveClusters: vi.fn(),
    clearOverhangs: vi.fn(),
    ...apiOverrides,
  }
  const deps = {
    store, api,
    libraryPanel: { refresh: vi.fn() },
    resetForNewDesign: vi.fn(),
    showWelcome: vi.fn(),
    hideWelcome: vi.fn(),
    renderRecentMenu: vi.fn(),
    setWorkspacePath: vi.fn(),
    setFileName: vi.fn(),
    setSyncStatus: vi.fn(),
    saveAs: vi.fn(),
    setFileHandle: vi.fn(),
  }
  return deps
}

describe('initImportMenu', () => {
  beforeEach(() => { clearDom(); vi.clearAllMocks() })

  it('returns its three callbacks and no-ops gracefully without DOM', () => {
    const out = initImportMenu(makeDeps())
    expect(typeof out.importCadnanoWithAutodetection).toBe('function')
    expect(typeof out.importScadnanoWithAutodetection).toBe('function')
    expect(typeof out.runPdbImport).toBe('function')
  })

  it('wires the PDB menu item to open the modal with runPdbImport as onResult', () => {
    mountIds(['menu-file-import-cadnano', 'menu-file-import-scadnano', 'menu-file-import-pdb'])
    const out = initImportMenu(makeDeps())
    document.getElementById('menu-file-import-pdb').dispatchEvent(new MouseEvent('click'))
    expect(openImportPdbModal).toHaveBeenCalledTimes(1)
    expect(openImportPdbModal.mock.calls[0][0].onResult).toBe(out.runPdbImport)
  })
})

describe('runPdbImport', () => {
  beforeEach(() => { clearDom(); vi.clearAllMocks() })

  it('toasts and returns null when the import fails', async () => {
    const deps = makeDeps({ lastError: { message: 'bad id' } }, { importPdbAuto: vi.fn().mockResolvedValue(null) })
    const { runPdbImport } = initImportMenu(deps)
    const r = await runPdbImport({ rcsb_id: '1abc' })
    expect(r).toBeNull()
    expect(showToast).toHaveBeenCalledWith('PDB import failed: bad id', { severity: 'error' })
    expect(deps.api.syncDesignResponse).not.toHaveBeenCalled()
  })

  it('returns the json unchanged when a DNA decision is needed (no sync)', async () => {
    const json = { needs_dna_decision: true }
    const deps = makeDeps({}, { importPdbAuto: vi.fn().mockResolvedValue(json) })
    const { runPdbImport } = initImportMenu(deps)
    const r = await runPdbImport({})
    expect(r).toBe(json)
    expect(deps.api.syncDesignResponse).not.toHaveBeenCalled()
    expect(deps.resetForNewDesign).not.toHaveBeenCalled()
  })

  it('preserves the decision response revision for the follow-up import', async () => {
    const importPdbAuto = vi.fn().mockResolvedValue({ imported: { protein: true }, protein: { name: 'P', atom_count: 1 } })
    const deps = makeDeps({}, { importPdbAuto, currentRevisionWatermark: vi.fn(() => 4) })
    const { runPdbImport } = initImportMenu(deps)
    await runPdbImport({ pdbId: '8SCP', removeDnaFromProtein: true, expectedRevision: 17 })
    expect(importPdbAuto).toHaveBeenCalledWith(expect.objectContaining({ expectedRevision: 17 }))
  })

  it('imports a DNA design: resets, syncs, hides welcome, toasts', async () => {
    const json = { imported: { dna: true }, import_warnings: ['watch out'] }
    const deps = makeDeps({}, { importPdbAuto: vi.fn().mockResolvedValue(json) })
    const { runPdbImport } = initImportMenu(deps)
    await runPdbImport({})
    expect(deps.resetForNewDesign).toHaveBeenCalledTimes(1)
    expect(deps.api.syncDesignResponse).toHaveBeenCalledWith(json)
    expect(deps.hideWelcome).toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith('watch out', 5000)
    expect(showToast).toHaveBeenCalledWith('Imported DNA design', 4000)
  })

  it('imports a protein without resetting the design', async () => {
    const json = { imported: { protein: true }, protein: { name: 'GFP', atom_count: 1234 } }
    const deps = makeDeps({}, { importPdbAuto: vi.fn().mockResolvedValue(json) })
    const { runPdbImport } = initImportMenu(deps)
    await runPdbImport({})
    expect(deps.resetForNewDesign).not.toHaveBeenCalled()
    expect(deps.api.syncDesignResponse).toHaveBeenCalledWith(json)
    expect(showToast).toHaveBeenCalledWith('Imported protein GFP (1234 atoms)', 4000)
  })

  it('keeps a library-only protein out of the design sync', async () => {
    const json = {
      imported: { protein: true }, protein_placement: 'library',
      protein: { name: 'GFP', atom_count: 1234 },
    }
    const deps = makeDeps({}, { importPdbAuto: vi.fn().mockResolvedValue(json) })
    const { runPdbImport } = initImportMenu(deps)
    await runPdbImport({})
    expect(deps.api.syncDesignResponse).not.toHaveBeenCalled()
    expect(deps.hideWelcome).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith(
      'Imported protein GFP in library (1234 atoms)', 4000)
  })

  it('combines DNA + protein in one summary toast', async () => {
    const json = { imported: { dna: true, protein: true }, protein: { name: 'GFP', atom_count: 10 } }
    const deps = makeDeps({}, { importPdbAuto: vi.fn().mockResolvedValue(json) })
    const { runPdbImport } = initImportMenu(deps)
    await runPdbImport({})
    expect(showToast).toHaveBeenCalledWith('Imported DNA design + protein GFP (10 atoms)', 4000)
  })
})

describe.each([
  ['caDNAno', 'importCadnanoWithAutodetection', 'importCadnanoDesign', 'sample.json'],
  ['scadnano', 'importScadnanoWithAutodetection', 'importScadnanoDesign', 'sample.sc'],
])('%s imported group omission', (_format, callback, importMethod, filename) => {
  let deps, imported, pickFile
  const destination = { path: 'parts/sample.nadoc', name: 'sample.nadoc', includeClusters: false, includeOverhangs: false }
  beforeEach(() => {
    clearDom(); vi.clearAllMocks(); openFileBrowser.mockReset()
    imported = { id: 'imported', metadata: { name: 'Imported' },
      cluster_transforms: [{ id: 'default', is_default: true }, { id: 'a' }, { id: 'b', is_default: false }],
      overhangs: [{ id: 'overhang' }] }
    deps = makeDeps({ currentDesign: imported, lastError: { message: 'Group is needed by a deformation' } })
    deps.api[importMethod].mockResolvedValue({ design: imported })
    deps.api.saveDesignAs.mockResolvedValue({ saved: true })
    pickFile = { name: filename, text: vi.fn().mockResolvedValue('{}') }
    vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(function () {
      Object.defineProperty(this, 'files', { configurable: true, value: pickFile ? [pickFile] : [] })
      this.onchange?.()
    })
    openFileBrowser.mockResolvedValue(destination)
  })
  afterEach(() => { vi.restoreAllMocks(); clearDom() })
  const run = () => initImportMenu(deps)[callback]()

  it('waits for one atomic nondefault-group dissolve before other omissions and save', async () => {
    let resolve
    deps.api.dissolveClusters.mockImplementation(() => new Promise(done => { resolve = done }))
    const pending = run()
    await vi.waitFor(() => expect(deps.api.dissolveClusters).toHaveBeenCalledExactlyOnceWith(['a', 'b']))
    expect(deps.api.deleteCluster).not.toHaveBeenCalled()
    expect(deps.api.clearOverhangs).not.toHaveBeenCalled(); expect(deps.api.saveDesignAs).not.toHaveBeenCalled()
    const accepted = { ...imported, cluster_transforms: [imported.cluster_transforms[0]] }
    deps.store.setState({ currentDesign: accepted }); resolve({ design: accepted }); await pending
    expect(deps.api.clearOverhangs).toHaveBeenCalledTimes(1)
    expect(deps.api.saveDesignAs).toHaveBeenCalledExactlyOnceWith(destination.path, false)
    expect(deps.setWorkspacePath).toHaveBeenCalledWith(destination.path)
  })

  it.each(['null', 'throw'])('retains the imported model and stops save on %s dissolve failure', async failure => {
    if (failure === 'throw') deps.api.dissolveClusters.mockRejectedValue(new Error('Dissolve connection lost'))
    else deps.api.dissolveClusters.mockResolvedValue(null)
    await expect(run()).resolves.toBeUndefined()
    expect(deps.api.dissolveClusters).toHaveBeenCalledExactlyOnceWith(['a', 'b'])
    expect(deps.api.deleteCluster).not.toHaveBeenCalled(); expect(deps.api.clearOverhangs).not.toHaveBeenCalled()
    expect(deps.api.saveDesignAs).not.toHaveBeenCalled(); expect(deps.setWorkspacePath).not.toHaveBeenCalled()
    expect(deps.store.getState().currentDesign).toBe(imported)
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining(failure === 'throw' ? 'Dissolve connection lost' : 'Group is needed by a deformation'), { severity: 'error' })
  })

  it.each(['retained groups', 'replaced document'])('does not save after a non-null stale reply with %s', async stale => {
    let resolve
    deps.api.dissolveClusters.mockImplementation(() => new Promise(done => { resolve = done }))
    const pending = run()
    await vi.waitFor(() => expect(deps.api.dissolveClusters).toHaveBeenCalledTimes(1))
    const current = stale === 'retained groups' ? imported : { ...imported, id: 'replacement', cluster_transforms: [] }
    deps.store.setState({ currentDesign: current })
    resolve({ design: { ...imported, cluster_transforms: [] } }); await pending
    expect(deps.store.getState().currentDesign).toBe(current)
    expect(deps.api.clearOverhangs).not.toHaveBeenCalled(); expect(deps.api.saveDesignAs).not.toHaveBeenCalled()
    expect(deps.setWorkspacePath).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('not current'), { severity: 'error' })
  })

  it('does not omit groups or save after the destination dialog is cancelled', async () => {
    openFileBrowser.mockResolvedValue(null); await run()
    expect(deps.api.dissolveClusters).not.toHaveBeenCalled(); expect(deps.api.deleteCluster).not.toHaveBeenCalled()
    expect(deps.api.saveDesignAs).not.toHaveBeenCalled(); expect(deps.store.getState().currentDesign).toBe(imported)
  })

  it('does not import or change anything when the file picker is cancelled', async () => {
    pickFile = null; await run()
    expect(deps.api[importMethod]).not.toHaveBeenCalled(); expect(deps.resetForNewDesign).not.toHaveBeenCalled()
    expect(openFileBrowser).not.toHaveBeenCalled(); expect(deps.api.dissolveClusters).not.toHaveBeenCalled()
    expect(deps.api.saveDesignAs).not.toHaveBeenCalled()
  })

  it.each(['keep', 'empty'])('does not send a dissolve for %s selection', async selection => {
    if (selection === 'keep') openFileBrowser.mockResolvedValue({ ...destination, includeClusters: true })
    else imported.cluster_transforms = [imported.cluster_transforms[0]]
    await run()
    expect(deps.api.dissolveClusters).not.toHaveBeenCalled(); expect(deps.api.deleteCluster).not.toHaveBeenCalled()
    expect(deps.api.saveDesignAs).toHaveBeenCalledTimes(1)
  })
})
