/**
 * Tests for the file-IO operations factory (file_io.js, extraction #52).
 *
 * Every operation moved verbatim out of main.js; these drive the factory with a
 * mock store/api + get/set shims and assert the side-effects (handle writes,
 * status updates, broadcasts, state writes via the injected setters).
 *
 * The File System Access "open" picker (_pickOpenFile) was dropped (dead); the
 * remaining ops are reachable here because they take their handle/path as args
 * or go through the injected openFileBrowser (mocked).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

vi.mock('./toast.js', () => ({
  showToast: vi.fn(),
  showPersistentToast: vi.fn(),
  dismissToast: vi.fn(),
}))
vi.mock('./file_browser.js', () => ({ openFileBrowser: vi.fn() }))
vi.mock('../shared/broadcast.js', () => ({
  nadocBroadcast: { emit: vi.fn() },
}))
vi.mock('../shared/doc_id.js', () => ({
  docHeaders: () => ({ 'X-NADOC-Doc': 'TESTDOC' }),
}))

import { showToast } from './toast.js'
import { openFileBrowser } from './file_browser.js'
import { nadocBroadcast } from '../shared/broadcast.js'
import { initFileIo, initFileOpen, initFileSave } from './file_io.js'

/** Build a factory with mutable backing state + recording shims. */
function makeFactory(overrides = {}) {
  const state = {
    fileHandle: 'OLD_HANDLE',
    assemblyFileHandle: 'OLD_ASM_HANDLE',
    assemblyName: 'OldAsm',
    workspacePath: null,
    assemblyWorkspacePath: null,
    partEditContext: null,
    ...overrides.state,
  }
  const store = createMockStore({
    currentDesign: { metadata: { name: 'MyDesign' } },
    currentAssembly: { metadata: { name: 'MyAssembly' } },
    ...overrides.storeState,
  })
  const api = {
    patchInstanceDesign: vi.fn(async () => ({ ok: true })),
    saveDesignAs: vi.fn(async () => ({ ok: true })),
    saveAssemblyAs: vi.fn(async () => ({ ok: true })),
    getAssemblyContent: vi.fn(async () => '{"assembly":1}'),
    ...overrides.api,
  }
  const deps = {
    store, api,
    setSyncStatus: vi.fn(),
    syncLog: vi.fn(),
    libraryPanel: { refresh: vi.fn() },
    updateAssemblyTitle: vi.fn(),
    setWorkspacePath: vi.fn((v) => { state.workspacePath = v }),
    setFileName: vi.fn(),
    setAssemblyWorkspacePath: vi.fn((v) => { state.assemblyWorkspacePath = v }),
    setFileHandle: vi.fn((v) => { state.fileHandle = v }),
    setAssemblyFileHandle: vi.fn((v) => { state.assemblyFileHandle = v }),
    setAssemblyName: vi.fn((v) => { state.assemblyName = v }),
    getWorkspacePath: () => state.workspacePath,
    getAssemblyWorkspacePath: () => state.assemblyWorkspacePath,
    getAssemblyName: () => state.assemblyName,
    getPartEditContext: () => state.partEditContext,
  }
  return { fileIo: initFileIo(deps), deps, state, store, api }
}

/** A writable file handle that records what was written. */
function makeHandle({ throwOnWrite = false } = {}) {
  const written = []
  return {
    written,
    createWritable: vi.fn(async () => ({
      write: vi.fn(async (c) => { if (throwOnWrite) throw new Error('disk full'); written.push(c) }),
      close: vi.fn(async () => {}),
    })),
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('fetch', vi.fn())
  mountIds(['mode-indicator'])
})
afterEach(() => {
  clearDom()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

// ── getDesignContent ─────────────────────────────────────────────────────────

describe('getDesignContent', () => {
  it('returns the response text on a 200', async () => {
    fetch.mockResolvedValueOnce({ ok: true, text: async () => '{"design":1}' })
    const { fileIo } = makeFactory()
    expect(await fileIo.getDesignContent()).toBe('{"design":1}')
    expect(fetch).toHaveBeenCalledWith('/api/design/export', { headers: { 'X-NADOC-Doc': 'TESTDOC' } })
  })
  it('returns null on a non-ok response', async () => {
    fetch.mockResolvedValueOnce({ ok: false })
    const { fileIo } = makeFactory()
    expect(await fileIo.getDesignContent()).toBe(null)
  })
})

// ── saveToHandle ─────────────────────────────────────────────────────────────

describe('saveToHandle', () => {
  it('writes the design content to the handle and returns true', async () => {
    fetch.mockResolvedValueOnce({ ok: true, text: async () => 'CONTENT' })
    const { fileIo } = makeFactory()
    const handle = makeHandle()
    expect(await fileIo.saveToHandle(handle)).toBe(true)
    expect(handle.written).toEqual(['CONTENT'])
  })
  it('returns false + toasts when the server read fails', async () => {
    fetch.mockResolvedValueOnce({ ok: false })
    const { fileIo } = makeFactory()
    expect(await fileIo.saveToHandle(makeHandle())).toBe(false)
    expect(showToast).toHaveBeenCalledWith('Failed to read design from server.', { severity: 'error' })
  })
  it('returns false + toasts on a write error', async () => {
    fetch.mockResolvedValueOnce({ ok: true, text: async () => 'CONTENT' })
    const { fileIo } = makeFactory()
    expect(await fileIo.saveToHandle(makeHandle({ throwOnWrite: true }))).toBe(false)
    expect(showToast).toHaveBeenCalledWith('Save failed: disk full', { severity: 'error' })
  })
})

// ── saveAs ───────────────────────────────────────────────────────────────────

describe('saveAs', () => {
  it('no-ops with a toast when there is no design', async () => {
    const { fileIo, deps } = makeFactory({ storeState: { currentDesign: null } })
    await fileIo.saveAs()
    expect(showToast).toHaveBeenCalledWith('No design to save.', { severity: 'error' })
    expect(openFileBrowser).not.toHaveBeenCalled()
    expect(deps.setSyncStatus).not.toHaveBeenCalled()
  })
  it('cancelling the dialog leaves all state untouched', async () => {
    openFileBrowser.mockResolvedValueOnce(null)
    const { fileIo, deps } = makeFactory()
    await fileIo.saveAs()
    expect(deps.setWorkspacePath).not.toHaveBeenCalled()
    expect(deps.setSyncStatus).not.toHaveBeenCalled()
  })
  it('on success clears the handle, sets path/name/status, refreshes the library', async () => {
    openFileBrowser.mockResolvedValueOnce({ path: 'workspace/x.nadoc', name: 'x' })
    const { fileIo, deps, state } = makeFactory()
    await fileIo.saveAs()
    expect(deps.api.saveDesignAs).toHaveBeenCalledWith('workspace/x.nadoc', false)
    expect(state.fileHandle).toBe(null)
    expect(deps.setWorkspacePath).toHaveBeenCalledWith('workspace/x.nadoc')
    expect(deps.setFileName).toHaveBeenCalledWith('x')
    expect(deps.setSyncStatus).toHaveBeenLastCalledWith('green', 'saved')
    expect(deps.libraryPanel.refresh).toHaveBeenCalled()
  })
  it('derives the suggested stem from the workspace path basename', async () => {
    openFileBrowser.mockResolvedValueOnce(null)
    const { fileIo } = makeFactory({ state: { workspacePath: 'workspace/sub/cool.nadoc' } })
    await fileIo.saveAs()
    expect(openFileBrowser).toHaveBeenCalledWith(expect.objectContaining({ suggestedName: 'cool' }))
  })
  it('on a save failure flips the status to red', async () => {
    openFileBrowser.mockResolvedValueOnce({ path: 'workspace/x.nadoc', name: 'x' })
    const { fileIo, deps } = makeFactory({ api: { saveDesignAs: vi.fn(async () => null) } })
    await fileIo.saveAs()
    expect(deps.setSyncStatus).toHaveBeenLastCalledWith('red', 'save error')
  })
})

// ── saveAssemblyToHandle ─────────────────────────────────────────────────────

describe('saveAssemblyToHandle', () => {
  it('writes the assembly content to the handle and returns true', async () => {
    const { fileIo } = makeFactory()
    const handle = makeHandle()
    expect(await fileIo.saveAssemblyToHandle(handle)).toBe(true)
    expect(handle.written).toEqual(['{"assembly":1}'])
  })
  it('returns false + toasts when the assembly read fails', async () => {
    const { fileIo } = makeFactory({ api: { getAssemblyContent: vi.fn(async () => null) } })
    expect(await fileIo.saveAssemblyToHandle(makeHandle())).toBe(false)
    expect(showToast).toHaveBeenCalledWith('Failed to read assembly from server.', { severity: 'error' })
  })
})

// ── saveAssemblyAs ───────────────────────────────────────────────────────────

describe('saveAssemblyAs', () => {
  it('on success clears the handle, sets name/path, updates the title, refreshes', async () => {
    openFileBrowser.mockResolvedValueOnce({ path: 'workspace/a.nass', name: 'a' })
    const { fileIo, deps, state } = makeFactory()
    await fileIo.saveAssemblyAs()
    expect(deps.api.saveAssemblyAs).toHaveBeenCalledWith('workspace/a.nass', false)
    expect(state.assemblyFileHandle).toBe(null)
    expect(state.assemblyName).toBe('a')
    expect(deps.setAssemblyWorkspacePath).toHaveBeenCalledWith('workspace/a.nass')
    expect(deps.updateAssemblyTitle).toHaveBeenCalled()
    expect(deps.libraryPanel.refresh).toHaveBeenCalled()
  })
  it('cancelling skips the save entirely', async () => {
    openFileBrowser.mockResolvedValueOnce(null)
    const { fileIo, deps } = makeFactory()
    await fileIo.saveAssemblyAs()
    expect(deps.api.saveAssemblyAs).not.toHaveBeenCalled()
    expect(deps.updateAssemblyTitle).not.toHaveBeenCalled()
  })
  it('falls back to the injected assembly name for the stem', async () => {
    openFileBrowser.mockResolvedValueOnce(null)
    const { fileIo } = makeFactory({ state: { assemblyName: 'NamedAsm', assemblyWorkspacePath: null } })
    await fileIo.saveAssemblyAs()
    expect(openFileBrowser).toHaveBeenCalledWith(expect.objectContaining({ suggestedName: 'NamedAsm' }))
  })
})

// ── savePartToAssembly ───────────────────────────────────────────────────────

describe('savePartToAssembly', () => {
  it('returns null when not editing a part', async () => {
    const { fileIo, deps } = makeFactory()   // partEditContext null
    expect(await fileIo.savePartToAssembly()).toBe(null)
    expect(deps.api.patchInstanceDesign).not.toHaveBeenCalled()
  })
  it('patches the instance design, broadcasts, and greens the status', async () => {
    fetch.mockResolvedValueOnce({ ok: true, text: async () => 'PART_CONTENT' })
    const { fileIo, deps } = makeFactory({
      state: { partEditContext: { instanceId: 'I7', name: 'Widget', assemblyDoc: 'ADOC' } },
    })
    const r = await fileIo.savePartToAssembly({ silent: true })
    expect(r).toEqual({ ok: true })
    expect(deps.api.patchInstanceDesign).toHaveBeenCalledWith('I7', 'PART_CONTENT', { docId: 'ADOC' })
    expect(nadocBroadcast.emit).toHaveBeenCalledWith('part-design-updated', { instanceId: 'I7' })
    expect(deps.setSyncStatus).toHaveBeenCalledWith('green', 'auto-saved to assembly')
  })
  it('non-silent updates the mode-indicator label', async () => {
    fetch.mockResolvedValueOnce({ ok: true, text: async () => 'PART_CONTENT' })
    const { fileIo } = makeFactory({
      state: { partEditContext: { instanceId: 'I7', name: 'Widget', assemblyDoc: 'ADOC' } },
    })
    await fileIo.savePartToAssembly({ silent: false })
    expect(document.getElementById('mode-indicator').textContent).toContain('Widget ✓ saved')
  })
  it('reds the status when the patch fails', async () => {
    fetch.mockResolvedValueOnce({ ok: true, text: async () => 'PART_CONTENT' })
    const { fileIo, deps } = makeFactory({
      state: { partEditContext: { instanceId: 'I7', name: 'Widget', assemblyDoc: 'ADOC' } },
      api: { patchInstanceDesign: vi.fn(async () => null) },
    })
    await fileIo.savePartToAssembly({ silent: true })
    expect(deps.setSyncStatus).toHaveBeenCalledWith('red', 'save error')
  })
})

// ── initFileOpen (open-orchestration, extraction #59) ────────────────────────

/**
 * Build the open-orchestration factory with recording shims. `enterAssemblyMode`
 * resolves the stashed build promise (simulating the assembly subscriber that
 * normally settles it) so the success path doesn't hang awaiting `built`.
 */
function makeOpenFactory(overrides = {}) {
  const state = {
    assemblyName: null, assemblyFileHandle: 'OLD_H', assemblyWorkspacePath: null,
    onProgress: undefined, settle: undefined,
  }
  const store = createMockStore({
    lastError: null,
    currentAssembly: { instances: [{ id: 'a', visible: true }] },
    ...overrides.storeState,
  })
  const api = {
    getLibraryFileContent: vi.fn(async () => ({ content: '{"x":1}' })),
    importDesign: vi.fn(async () => true),
    importAssembly: vi.fn(async () => true),
    ...overrides.api,
  }
  const deps = {
    store, api,
    showFileLoad: vi.fn(),
    flAppendLog: vi.fn(),
    flSetProgress: vi.fn(),
    flShowError: vi.fn(),
    flShowSuccess: vi.fn(async () => {}),
    resetForNewDesign: vi.fn(),
    setFileName: vi.fn(),
    setWorkspacePath: vi.fn(),
    hideWelcome: vi.fn(),
    showWelcome: vi.fn(),
    revealWorkspaceForEmptyPart: vi.fn(),
    fitToView: vi.fn(),
    enterAssemblyMode: vi.fn(() => { state.settle?.resolve() }),
    setAssemblyWorkspacePath: vi.fn((v) => { state.assemblyWorkspacePath = v }),
    setAssemblyName: vi.fn((v) => { state.assemblyName = v }),
    setAssemblyFileHandle: vi.fn((v) => { state.assemblyFileHandle = v }),
    setAssemblyLoadOnProgress: vi.fn((v) => { state.onProgress = v }),
    setAssemblyLoadSettle: vi.fn((v) => { state.settle = v }),
    ...overrides.deps,
  }
  return { fileOpen: initFileOpen(deps), deps, state, store, api }
}

describe('initFileOpen — openPartFromServer', () => {
  it('aborts with an error overlay when the server returns no content', async () => {
    const { fileOpen, deps } = makeOpenFactory({ api: { getLibraryFileContent: vi.fn(async () => ({ content: null })) } })
    await fileOpen.openPartFromServer('p/x.nadoc', 'x')
    expect(deps.flShowError).toHaveBeenCalledWith('Could not load part.')
    expect(deps.resetForNewDesign).not.toHaveBeenCalled()
    expect(deps.api.importDesign).not.toHaveBeenCalled()
  })
  it('on a successful import sets identity, reveals the workspace, and frames', async () => {
    const { fileOpen, deps } = makeOpenFactory()
    await fileOpen.openPartFromServer('p/x.nadoc', 'NiceName')
    expect(deps.resetForNewDesign).toHaveBeenCalled()
    expect(deps.api.importDesign).toHaveBeenCalledWith('{"x":1}')
    expect(deps.setFileName).toHaveBeenCalledWith('NiceName')
    expect(deps.setWorkspacePath).toHaveBeenCalledWith('p/x.nadoc')
    expect(deps.hideWelcome).toHaveBeenCalled()
    expect(deps.revealWorkspaceForEmptyPart).toHaveBeenCalled()
    expect(deps.fitToView).toHaveBeenCalled()
    expect(deps.flShowSuccess).toHaveBeenCalledWith('Part loaded successfully')
    expect(deps.showWelcome).not.toHaveBeenCalled()
  })
  it('falls back to the path as the filename when no name is given', async () => {
    const { fileOpen, deps } = makeOpenFactory()
    await fileOpen.openPartFromServer('p/x.nadoc')
    expect(deps.setFileName).toHaveBeenCalledWith('p/x.nadoc')
  })
  it('on import failure shows the error and returns to the welcome screen', async () => {
    const { fileOpen, deps } = makeOpenFactory({
      api: { importDesign: vi.fn(async () => false) },
      storeState: { lastError: { message: 'bad json' } },
    })
    await fileOpen.openPartFromServer('p/x.nadoc', 'x')
    expect(deps.flShowError).toHaveBeenCalledWith('Failed to import part.')
    expect(deps.showWelcome).toHaveBeenCalled()
    expect(deps.fitToView).not.toHaveBeenCalled()
  })
  it('catches a fetch exception and surfaces the load error', async () => {
    const { fileOpen, deps } = makeOpenFactory({
      api: { getLibraryFileContent: vi.fn(async () => { throw new Error('network') }) },
    })
    await fileOpen.openPartFromServer('p/x.nadoc', 'x')
    expect(deps.flShowError).toHaveBeenCalledWith('Could not load part.')
  })
})

describe('initFileOpen — openAssemblyFromServer', () => {
  it('aborts with an error overlay when the server returns no content', async () => {
    const { fileOpen, deps } = makeOpenFactory({ api: { getLibraryFileContent: vi.fn(async () => ({ content: null })) } })
    await fileOpen.openAssemblyFromServer('p/a.nass')
    expect(deps.flShowError).toHaveBeenCalledWith('Could not load assembly.')
    expect(deps.enterAssemblyMode).not.toHaveBeenCalled()
  })
  it('clears the stash and shows the error when the import fails', async () => {
    const { fileOpen, deps } = makeOpenFactory({
      api: { importAssembly: vi.fn(async () => false) },
      storeState: { lastError: { message: 'corrupt' } },
    })
    await fileOpen.openAssemblyFromServer('p/a.nass')
    expect(deps.setAssemblyLoadOnProgress).toHaveBeenLastCalledWith(null)
    expect(deps.setAssemblyLoadSettle).toHaveBeenLastCalledWith(null)
    expect(deps.flShowError).toHaveBeenCalledWith('Failed to import assembly.')
    expect(deps.enterAssemblyMode).not.toHaveBeenCalled()
  })
  it('on a visible-instance load stashes progress, sets identity, enters mode, and succeeds', async () => {
    const { fileOpen, deps, state } = makeOpenFactory()
    await fileOpen.openAssemblyFromServer('p/a.nass')
    // stash was armed with a real progress callback before the import
    expect(typeof state.onProgress).toBe('function')
    expect(state.assemblyName).toBe('p/a')          // .nass stripped
    expect(state.assemblyFileHandle).toBe(null)
    expect(deps.setAssemblyWorkspacePath).toHaveBeenCalledWith('p/a.nass')
    expect(deps.enterAssemblyMode).toHaveBeenCalled()
    expect(deps.flShowSuccess).toHaveBeenCalledWith('Assembly loaded successfully')
  })
  it('the stashed onProgress callback drives the overlay per build stage', async () => {
    const { fileOpen, deps, state } = makeOpenFactory()
    await fileOpen.openAssemblyFromServer('p/a.nass')
    deps.flAppendLog.mockClear()
    deps.flSetProgress.mockClear()
    state.onProgress({ stage: 'instance_built', done: 1, total: 2, name: 'PartA' })
    expect(deps.flSetProgress).toHaveBeenCalledWith(78, 'Part 1 / 2')   // 55 + round(1/2*45)
    expect(deps.flAppendLog).toHaveBeenCalledWith('  ✓ PartA', 'success')
  })
  it('an empty assembly resolves immediately without awaiting the subscriber', async () => {
    const { fileOpen, deps, state } = makeOpenFactory({
      storeState: { currentAssembly: { instances: [] } },
    })
    await fileOpen.openAssemblyFromServer('p/empty.nass')
    // stash released before mode-enter; build promise self-resolved
    expect(deps.setAssemblyLoadSettle).toHaveBeenLastCalledWith(null)
    expect(state.settle).toBe(null)
    expect(deps.enterAssemblyMode).toHaveBeenCalled()
    expect(deps.flShowSuccess).toHaveBeenCalledWith('Assembly loaded successfully')
  })
})

// ── initFileSave (Save / Save As dispatch, extraction #60) ───────────────────

/**
 * Build the save-dispatch factory with recording shims over a mock fileIo /
 * syncBadge and mutable file/path/export-rep state read through getters.
 * `selfSavedPaths` is a real Set so the add/delete suppression is observable.
 */
function makeSaveFactory(overrides = {}) {
  const state = {
    workspacePath: null,
    fileHandle: null,
    assemblyWorkspacePath: null,
    assemblyFileHandle: null,
    exportRepActive: false,
    ...overrides.state,
  }
  const store = createMockStore({
    assemblyActive: false,
    currentDesign: { metadata: { name: 'MyDesign' } },
    currentAssembly: { metadata: { name: 'MyAssembly' } },
    ...overrides.storeState,
  })
  const api = {
    saveDesignToWorkspace: vi.fn(async () => ({ ok: true })),
    saveAssemblyAs: vi.fn(async () => ({ path: 'a/saved.nass' })),
    ...overrides.api,
  }
  const fileIo = {
    saveToHandle: vi.fn(async () => true),
    saveAs: vi.fn(async () => {}),
    saveAssemblyToHandle: vi.fn(async () => true),
    saveAssemblyAs: vi.fn(async () => {}),
    ...overrides.fileIo,
  }
  const syncBadge = { setSyncStatus: vi.fn(), syncLog: vi.fn() }
  const selfSavedPaths = new Set()
  const deps = {
    store, api, fileIo, syncBadge, selfSavedPaths,
    getWorkspacePath:         () => state.workspacePath,
    getFileHandle:            () => state.fileHandle,
    getAssemblyWorkspacePath: () => state.assemblyWorkspacePath,
    getAssemblyFileHandle:    () => state.assemblyFileHandle,
    getExportRepActive:       () => state.exportRepActive,
    setAssemblyWorkspacePath: vi.fn((v) => { state.assemblyWorkspacePath = v }),
  }
  return { fileSave: initFileSave(deps), deps, state, store, api, fileIo, syncBadge, selfSavedPaths }
}

describe('initFileSave — saveDispatch (design mode)', () => {
  it('toasts and bails when there is no current design', async () => {
    const { fileSave, fileIo } = makeSaveFactory({ storeState: { currentDesign: null } })
    await fileSave.saveDispatch()
    expect(showToast).toHaveBeenCalledWith('No design to save.', { severity: 'error' })
    expect(fileIo.saveAs).not.toHaveBeenCalled()
  })
  it('with a workspace path: logs, sets status, self-marks (then clears after 5s), and saves', async () => {
    vi.useFakeTimers()
    const { fileSave, api, syncBadge, selfSavedPaths } = makeSaveFactory({ state: { workspacePath: 'w/d.nadoc' } })
    await fileSave.saveDispatch()
    expect(syncBadge.syncLog).toHaveBeenCalledWith('info', 'SAVE', 'explicit save → w/d.nadoc')
    expect(syncBadge.setSyncStatus).toHaveBeenCalledWith('yellow', 'saving…')
    expect(selfSavedPaths.has('w/d.nadoc')).toBe(true)
    expect(api.saveDesignToWorkspace).toHaveBeenCalledWith('w/d.nadoc')
    expect(syncBadge.setSyncStatus).toHaveBeenLastCalledWith('green', 'saved')
    vi.advanceTimersByTime(5000)
    expect(selfSavedPaths.has('w/d.nadoc')).toBe(false)
  })
  it('with a workspace path AND a file handle, also mirrors to the handle', async () => {
    vi.useFakeTimers()
    const { fileSave, fileIo } = makeSaveFactory({ state: { workspacePath: 'w/d.nadoc', fileHandle: 'H' } })
    await fileSave.saveDispatch()
    expect(fileIo.saveToHandle).toHaveBeenCalledWith('H')
  })
  it('with only a file handle (no workspace path), saves to the handle', async () => {
    const { fileSave, fileIo, api } = makeSaveFactory({ state: { fileHandle: 'H' } })
    await fileSave.saveDispatch()
    expect(fileIo.saveToHandle).toHaveBeenCalledWith('H')
    expect(api.saveDesignToWorkspace).not.toHaveBeenCalled()
  })
  it('with neither path nor handle, falls back to Save As', async () => {
    const { fileSave, fileIo } = makeSaveFactory()
    await fileSave.saveDispatch()
    expect(fileIo.saveAs).toHaveBeenCalled()
  })
  it('routes to the assembly save path when assemblyActive', async () => {
    const { fileSave, api } = makeSaveFactory({
      storeState: { assemblyActive: true },
      state: { assemblyWorkspacePath: 'a/x.nass' },
    })
    await fileSave.saveDispatch()
    expect(api.saveAssemblyAs).toHaveBeenCalledWith('a/x.nass')
  })
})

describe('initFileSave — saveAsDispatch', () => {
  it('in design mode delegates straight to fileIo.saveAs', async () => {
    const { fileSave, fileIo } = makeSaveFactory()
    await fileSave.saveAsDispatch()
    expect(fileIo.saveAs).toHaveBeenCalled()
  })
  it('in assembly mode routes to the guarded assembly Save As', async () => {
    const { fileSave, fileIo } = makeSaveFactory({ storeState: { assemblyActive: true } })
    await fileSave.saveAsDispatch()
    expect(fileIo.saveAssemblyAs).toHaveBeenCalled()
  })
})

describe('initFileSave — saveAssembly', () => {
  it('toasts and bails when there is no current assembly', async () => {
    const { fileSave, fileIo } = makeSaveFactory({ storeState: { currentAssembly: null } })
    await fileSave.saveAssembly()
    expect(showToast).toHaveBeenCalledWith('No assembly to save.', { severity: 'error' })
    expect(fileIo.saveAssemblyAs).not.toHaveBeenCalled()
  })
  it('warns and bails while an export-rep upgrade is in flight', async () => {
    const { fileSave, api } = makeSaveFactory({ state: { exportRepActive: true } })
    await fileSave.saveAssembly()
    expect(showToast).toHaveBeenCalledWith('Export in progress — try saving again in a moment.', { severity: 'warning' })
    expect(api.saveAssemblyAs).not.toHaveBeenCalled()
  })
  it('with a workspace path: saves, persists the returned path, mirrors to the handle', async () => {
    const { fileSave, api, fileIo, deps } = makeSaveFactory({
      state: { assemblyWorkspacePath: 'a/x.nass', assemblyFileHandle: 'AH' },
    })
    await fileSave.saveAssembly()
    expect(api.saveAssemblyAs).toHaveBeenCalledWith('a/x.nass')
    expect(deps.setAssemblyWorkspacePath).toHaveBeenCalledWith('a/saved.nass')
    expect(fileIo.saveAssemblyToHandle).toHaveBeenCalledWith('AH')
  })
  it('with only a handle (no workspace path), saves to the handle', async () => {
    const { fileSave, fileIo, api } = makeSaveFactory({ state: { assemblyFileHandle: 'AH' } })
    await fileSave.saveAssembly()
    expect(fileIo.saveAssemblyToHandle).toHaveBeenCalledWith('AH')
    expect(api.saveAssemblyAs).not.toHaveBeenCalled()
  })
  it('with neither path nor handle, falls back to assembly Save As', async () => {
    const { fileSave, fileIo } = makeSaveFactory()
    await fileSave.saveAssembly()
    expect(fileIo.saveAssemblyAs).toHaveBeenCalled()
  })
})

describe('initFileSave — saveAssemblyAsGuarded', () => {
  it('toasts and bails with no assembly', async () => {
    const { fileSave, fileIo } = makeSaveFactory({ storeState: { currentAssembly: null } })
    await fileSave.saveAssemblyAsGuarded()
    expect(showToast).toHaveBeenCalledWith('No assembly to save.', { severity: 'error' })
    expect(fileIo.saveAssemblyAs).not.toHaveBeenCalled()
  })
  it('warns and bails during an export-rep upgrade', async () => {
    const { fileSave, fileIo } = makeSaveFactory({ state: { exportRepActive: true } })
    await fileSave.saveAssemblyAsGuarded()
    expect(showToast).toHaveBeenCalledWith('Export in progress — try saving again in a moment.', { severity: 'warning' })
    expect(fileIo.saveAssemblyAs).not.toHaveBeenCalled()
  })
  it('otherwise delegates to assembly Save As', async () => {
    const { fileSave, fileIo } = makeSaveFactory()
    await fileSave.saveAssemblyAsGuarded()
    expect(fileIo.saveAssemblyAs).toHaveBeenCalled()
  })
})
