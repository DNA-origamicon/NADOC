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
import { initFileIo } from './file_io.js'

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
