import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'

// Mock the low-level poller so we can (a) avoid real timers/fetch and (b) capture
// the `onChange` callback the factory registers, then drive it with synthetic
// connection events.
let _capturedOnChange = null
vi.mock('../shared/connection_monitor.js', () => ({
  start: vi.fn(({ onChange } = {}) => { _capturedOnChange = onChange }),
}))

// Mock the cross-tab broadcast so the design auto-save's `emit('file-saved')` is
// observable and never touches a real BroadcastChannel in jsdom.
vi.mock('../shared/broadcast.js', () => ({
  nadocBroadcast: { emit: vi.fn(), onMessage: vi.fn(), isSameDoc: vi.fn(() => true) },
}))

import { initConnectionMonitor, initAutosaveSync } from './lifecycle.js'
import * as connectionMonitor from '../shared/connection_monitor.js'
import { nadocBroadcast } from '../shared/broadcast.js'

// A store mock that also supports `subscribeSlice(name, cb)` (the autosave
// subscribers use it). Captures callbacks per slice so tests can drive them.
function createSliceStore(initialState = {}) {
  let state = { ...initialState }
  const slices = {}
  return {
    getState: () => state,
    subscribeSlice: (name, cb) => { (slices[name] ??= []).push(cb) },
    // drive a slice: shallow-merge patch and fire that slice's subscribers
    _emitSlice: (name, patch) => {
      const prev = state
      state = { ...state, ...patch }
      for (const cb of (slices[name] ?? [])) cb(state, prev)
    },
    _hasSlice: (name) => (slices[name] ?? []).length > 0,
  }
}

function makeAutosaveDeps(overrides = {}) {
  const store = createSliceStore({
    assemblyActive: false,
    currentAssembly: null,
    ...(overrides.state ?? {}),
  })
  let _captureLibHandler = null
  const deps = {
    store,
    api: {
      wasLastDesignSyncTransient: vi.fn(() => false),
      saveDesignToWorkspace: vi.fn().mockResolvedValue({}),
      saveAssemblyAs: vi.fn().mockResolvedValue({ path: '/ws/a.nass' }),
      getLibraryFileContent: vi.fn().mockResolvedValue({ content: '{}' }),
      importDesign: vi.fn().mockResolvedValue({}),
      subscribeLibraryEvents: vi.fn((cb) => { _captureLibHandler = cb }),
    },
    fileIo: { savePartToAssembly: vi.fn() },
    syncBadge: { setSyncStatus: vi.fn(), syncLog: vi.fn() },
    libraryPanel: { refresh: vi.fn() },
    getAssemblyRefresh: () => ({ requestRefresh: vi.fn() }),
    getPartEditContext: () => null,
    getWorkspacePath: () => null,
    getAssemblyWorkspacePath: () => null,
    setAssemblyWorkspacePath: vi.fn(),
    ...overrides.deps,
  }
  return { store, deps, getLibHandler: () => _captureLibHandler }
}

function makeDeps(overrides = {}) {
  const store = createMockStore({
    assemblyActive: false,
    currentAssembly: null,
    ...(overrides.state ?? {}),
  })
  const deps = {
    store,
    api: {
      resetRevisionWatermark: vi.fn(),
      getAssembly: vi.fn().mockResolvedValue({}),
      getDesign: vi.fn().mockResolvedValue({}),
      getGeometry: vi.fn().mockResolvedValue({}),
      getPersistedDesign: vi.fn().mockReturnValue(null),
      importDesign: vi.fn().mockResolvedValue({}),
    },
    assemblyRenderer: {
      invalidateInstance: vi.fn(),
      rebuild: vi.fn().mockResolvedValue(undefined),
      rebuildLinkers: vi.fn().mockResolvedValue(undefined),
    },
    setSyncStatus: vi.fn(),
    syncLog: vi.fn(),
    setReloadingFromSSE: vi.fn(),
    ...overrides.deps,
  }
  return deps
}

describe('initConnectionMonitor', () => {
  beforeEach(() => {
    _capturedOnChange = null
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('starts the poller with an onChange callback and returns recoverAfterRestart', () => {
    const deps = makeDeps()
    const api = initConnectionMonitor(deps)
    expect(connectionMonitor.start).toHaveBeenCalledTimes(1)
    expect(typeof _capturedOnChange).toBe('function')
    expect(typeof api.recoverAfterRestart).toBe('function')
  })

  it('disconnected → red badge', async () => {
    const deps = makeDeps()
    initConnectionMonitor(deps)
    await _capturedOnChange({ type: 'disconnected' })
    expect(deps.setSyncStatus).toHaveBeenCalledWith('red', expect.stringContaining('reconnect'))
  })

  it('reconnected → green badge', async () => {
    const deps = makeDeps()
    initConnectionMonitor(deps)
    await _capturedOnChange({ type: 'reconnected' })
    expect(deps.setSyncStatus).toHaveBeenCalledWith('green', expect.stringContaining('reconnect'))
  })

  it('restarted → runs recovery then marks synced green', async () => {
    const deps = makeDeps({ deps: { } })
    deps.api.getPersistedDesign.mockReturnValue(null)
    initConnectionMonitor(deps)
    await _capturedOnChange({ type: 'restarted', health: { design_loaded: true } })
    // design_loaded branch: passive re-pull, guarded by the reloading flag
    expect(deps.setReloadingFromSSE).toHaveBeenNthCalledWith(1, true)
    expect(deps.api.getDesign).toHaveBeenCalled()
    expect(deps.api.getGeometry).toHaveBeenCalled()
    expect(deps.setReloadingFromSSE).toHaveBeenLastCalledWith(false)
    expect(deps.setSyncStatus).toHaveBeenLastCalledWith('green', 'synced')
  })

  it('restart recovery is re-entrancy guarded (second restart ignored while in flight)', async () => {
    const deps = makeDeps()
    // Hold the recovery in flight by deferring getDesign.
    let release
    deps.api.getDesign.mockReturnValue(new Promise((r) => { release = r }))
    initConnectionMonitor(deps)
    const first = _capturedOnChange({ type: 'restarted', health: { design_loaded: true } })
    // Second restart while first is still awaiting getDesign → should bail early.
    await _capturedOnChange({ type: 'restarted', health: { design_loaded: true } })
    expect(deps.api.getDesign).toHaveBeenCalledTimes(1)
    release({})
    await first
    expect(deps.api.getDesign).toHaveBeenCalledTimes(1)
  })

  describe('recoverAfterRestart branches', () => {
    it('assembly mode → re-pulls + rebuilds the assembly, ignores design_loaded', async () => {
      const deps = makeDeps({
        state: {
          assemblyActive: true,
          currentAssembly: { instances: [{ id: 'i1' }, { id: 'i2' }] },
        },
      })
      const { recoverAfterRestart } = initConnectionMonitor(deps)
      await recoverAfterRestart({ design_loaded: true })
      expect(deps.api.getAssembly).toHaveBeenCalled()
      expect(deps.assemblyRenderer.invalidateInstance).toHaveBeenCalledTimes(2)
      expect(deps.assemblyRenderer.rebuild).toHaveBeenCalled()
      expect(deps.assemblyRenderer.rebuildLinkers).toHaveBeenCalled()
      // design path NOT taken in assembly mode
      expect(deps.api.getDesign).not.toHaveBeenCalled()
      expect(deps.setReloadingFromSSE).not.toHaveBeenCalled()
    })

    it('design_loaded → passive re-pull wrapped in setReloadingFromSSE true/false', async () => {
      const deps = makeDeps()
      const { recoverAfterRestart } = initConnectionMonitor(deps)
      await recoverAfterRestart({ design_loaded: true })
      expect(deps.setReloadingFromSSE).toHaveBeenNthCalledWith(1, true)
      expect(deps.api.getDesign).toHaveBeenCalled()
      expect(deps.api.getGeometry).toHaveBeenCalled()
      expect(deps.setReloadingFromSSE).toHaveBeenLastCalledWith(false)
    })

    it('clears the reloading flag even when the re-pull throws', async () => {
      const deps = makeDeps()
      deps.api.getDesign.mockRejectedValue(new Error('boom'))
      const { recoverAfterRestart } = initConnectionMonitor(deps)
      await expect(recoverAfterRestart({ design_loaded: true })).rejects.toThrow('boom')
      expect(deps.setReloadingFromSSE).toHaveBeenNthCalledWith(1, true)
      expect(deps.setReloadingFromSSE).toHaveBeenLastCalledWith(false)
    })

    it('no design + no cache → does nothing destructive', async () => {
      const deps = makeDeps()
      deps.api.getPersistedDesign.mockReturnValue(null)
      const { recoverAfterRestart } = initConnectionMonitor(deps)
      await recoverAfterRestart({ design_loaded: false })
      expect(deps.api.importDesign).not.toHaveBeenCalled()
      expect(deps.api.getGeometry).not.toHaveBeenCalled()
    })

    it('no design + cache + user confirms → imports cached design from this tab', async () => {
      const deps = makeDeps()
      const cached = { strands: [] }
      deps.api.getPersistedDesign.mockReturnValue(cached)
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      const { recoverAfterRestart } = initConnectionMonitor(deps)
      await recoverAfterRestart({ design_loaded: false })
      expect(deps.api.importDesign).toHaveBeenCalledWith(JSON.stringify(cached))
      expect(deps.api.getGeometry).toHaveBeenCalled()
      confirmSpy.mockRestore()
    })

    it('no design + cache + user declines → no import', async () => {
      const deps = makeDeps()
      deps.api.getPersistedDesign.mockReturnValue({ strands: [] })
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
      const { recoverAfterRestart } = initConnectionMonitor(deps)
      await recoverAfterRestart({ design_loaded: false })
      expect(deps.api.importDesign).not.toHaveBeenCalled()
      confirmSpy.mockRestore()
    })

    it('always clears the stale-revision watermark first', async () => {
      const deps = makeDeps()
      const { recoverAfterRestart } = initConnectionMonitor(deps)
      await recoverAfterRestart({ design_loaded: true })
      expect(deps.api.resetRevisionWatermark).toHaveBeenCalled()
    })
  })
})

describe('initAutosaveSync', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('registers both autosave subscribers + the library-event handler and returns the API', () => {
    const { store, deps } = makeAutosaveDeps()
    const sync = initAutosaveSync(deps)
    expect(store._hasSlice('design')).toBe(true)
    expect(store._hasSlice('assembly')).toBe(true)
    expect(deps.api.subscribeLibraryEvents).toHaveBeenCalledTimes(1)
    expect(sync.selfSavedPaths instanceof Set).toBe(true)
    expect(sync.getReloadingFromSSE()).toBe(false)
    expect(sync.getSavingAssembly()).toBe(false)
    expect(typeof sync.setReloadingFromSSE).toBe('function')
    expect(typeof sync.markSameDocActivity).toBe('function')
    expect(typeof sync.handleLibraryEvent).toBe('function')
  })

  it('setReloadingFromSSE round-trips through getReloadingFromSSE', () => {
    const { deps } = makeAutosaveDeps()
    const sync = initAutosaveSync(deps)
    sync.setReloadingFromSSE(true)
    expect(sync.getReloadingFromSSE()).toBe(true)
    sync.setReloadingFromSSE(false)
    expect(sync.getReloadingFromSSE()).toBe(false)
  })

  // ── design auto-save ──
  it('skips a transient deform mutation (no save scheduled)', async () => {
    const { store, deps } = makeAutosaveDeps({ deps: { getWorkspacePath: () => '/ws/d.nadoc' } })
    deps.api.wasLastDesignSyncTransient.mockReturnValue(true)
    initAutosaveSync(deps)
    store._emitSlice('design', { currentDesign: { id: 'd1' } })
    await vi.advanceTimersByTimeAsync(2000)
    expect(deps.api.saveDesignToWorkspace).not.toHaveBeenCalled()
  })

  it('is suppressed while reloadingFromSSE is set', async () => {
    const { store, deps } = makeAutosaveDeps({ deps: { getWorkspacePath: () => '/ws/d.nadoc' } })
    const sync = initAutosaveSync(deps)
    sync.setReloadingFromSSE(true)
    store._emitSlice('design', { currentDesign: { id: 'd1' } })
    await vi.advanceTimersByTimeAsync(2000)
    expect(deps.api.saveDesignToWorkspace).not.toHaveBeenCalled()
  })

  it('debounced design save writes the file, broadcasts file-saved, marks self-saved', async () => {
    const { store, deps } = makeAutosaveDeps({ deps: { getWorkspacePath: () => '/ws/d.nadoc' } })
    const sync = initAutosaveSync(deps)
    store._emitSlice('design', { currentDesign: { id: 'd1' } })
    expect(deps.syncBadge.setSyncStatus).toHaveBeenCalledWith('yellow', 'saving…')
    await vi.advanceTimersByTimeAsync(1500)
    expect(deps.api.saveDesignToWorkspace).toHaveBeenCalledWith('/ws/d.nadoc')
    expect(nadocBroadcast.emit).toHaveBeenCalledWith('file-saved', { path: '/ws/d.nadoc' })
    expect(sync.selfSavedPaths.has('/ws/d.nadoc')).toBe(true)
    // self-save marker clears after 5s
    await vi.advanceTimersByTimeAsync(5000)
    expect(sync.selfSavedPaths.has('/ws/d.nadoc')).toBe(false)
  })

  it('part-edit context routes to savePartToAssembly (900ms, silent), not a workspace save', async () => {
    const { store, deps } = makeAutosaveDeps({
      deps: { getPartEditContext: () => ({ instanceId: 'i1' }), getWorkspacePath: () => '/ws/d.nadoc' },
    })
    initAutosaveSync(deps)
    store._emitSlice('design', { currentDesign: { id: 'd1' } })
    await vi.advanceTimersByTimeAsync(900)
    expect(deps.fileIo.savePartToAssembly).toHaveBeenCalledWith({ silent: true })
    expect(deps.api.saveDesignToWorkspace).not.toHaveBeenCalled()
  })

  // ── assembly auto-save ──
  it('debounced assembly save calls saveAssemblyAs and latches savingAssembly during the write', async () => {
    const { store, deps } = makeAutosaveDeps({ deps: { getAssemblyWorkspacePath: () => '/ws/a.nass' } })
    const sync = initAutosaveSync(deps)
    store._emitSlice('assembly', { currentAssembly: { id: 'a1' } })
    await vi.advanceTimersByTimeAsync(1500)
    expect(deps.api.saveAssemblyAs).toHaveBeenCalledWith('/ws/a.nass')
    expect(deps.setAssemblyWorkspacePath).toHaveBeenCalledWith('/ws/a.nass')
    expect(sync.selfSavedPaths.has('/ws/a.nass')).toBe(true)
    expect(sync.getSavingAssembly()).toBe(false)   // cleared in finally
  })

  it('assembly save is skipped when no assembly workspace path', async () => {
    const { store, deps } = makeAutosaveDeps()  // getAssemblyWorkspacePath → null
    initAutosaveSync(deps)
    store._emitSlice('assembly', { currentAssembly: { id: 'a1' } })
    await vi.advanceTimersByTimeAsync(1600)
    expect(deps.api.saveAssemblyAs).not.toHaveBeenCalled()
  })

  // ── library SSE handler ──
  it('ignores non file-changed/deleted events', () => {
    const { deps } = makeAutosaveDeps()
    const sync = initAutosaveSync(deps)
    sync.handleLibraryEvent({ type: 'whatever', path: '/x', file_type: 'part' })
    expect(deps.libraryPanel.refresh).not.toHaveBeenCalled()
  })

  it('skips a self-saved echo (no library refresh)', async () => {
    const { deps } = makeAutosaveDeps()
    const sync = initAutosaveSync(deps)
    sync.selfSavedPaths.add('/ws/d.nadoc')   // externally-mutated Set, shared by reference
    sync.handleLibraryEvent({ type: 'file-changed', path: '/ws/d.nadoc', file_type: 'part' })
    await vi.advanceTimersByTimeAsync(500)
    expect(deps.libraryPanel.refresh).not.toHaveBeenCalled()
  })

  it('a genuine external change debounces a single library refresh', async () => {
    const { deps } = makeAutosaveDeps()
    const sync = initAutosaveSync(deps)
    sync.handleLibraryEvent({ type: 'file-changed', path: '/ws/other.nadoc', file_type: 'part' })
    sync.handleLibraryEvent({ type: 'file-changed', path: '/ws/other2.nadoc', file_type: 'part' })
    await vi.advanceTimersByTimeAsync(400)
    expect(deps.libraryPanel.refresh).toHaveBeenCalledTimes(1)
  })

  it('assembly tab: a changed part file routes affected instances to the coalesced refresh', async () => {
    const requestRefresh = vi.fn()
    const { deps } = makeAutosaveDeps({
      state: {
        assemblyActive: true,
        currentAssembly: { instances: [{ id: 'i9', source: { type: 'file', path: '/ws/p.nadoc' } }] },
      },
      deps: { getAssemblyRefresh: () => ({ requestRefresh }) },
    })
    const sync = initAutosaveSync(deps)
    sync.handleLibraryEvent({ type: 'file-changed', path: '/ws/p.nadoc', file_type: 'part' })
    expect(requestRefresh).toHaveBeenCalledWith('i9', 'sse')
  })

  it('design tab: external edit of the open file reloads + toggles reloadingFromSSE around the import', async () => {
    const { deps } = makeAutosaveDeps({ deps: { getWorkspacePath: () => '/ws/open.nadoc' } })
    const sync = initAutosaveSync(deps)
    sync.handleLibraryEvent({ type: 'file-changed', path: '/ws/open.nadoc', file_type: 'part' })
    expect(sync.getReloadingFromSSE()).toBe(true)   // set synchronously before the await chain
    await vi.advanceTimersByTimeAsync(0)
    await Promise.resolve()
    expect(deps.api.getLibraryFileContent).toHaveBeenCalledWith('/ws/open.nadoc')
    expect(deps.api.importDesign).toHaveBeenCalledWith('{}')
    await vi.advanceTimersByTimeAsync(0)
    expect(sync.getReloadingFromSSE()).toBe(false)  // cleared in finally
  })

  it('design tab: reload is suppressed within the live same-doc activity window', async () => {
    const { deps } = makeAutosaveDeps({ deps: { getWorkspacePath: () => '/ws/open.nadoc' } })
    const sync = initAutosaveSync(deps)
    sync.markSameDocActivity()   // a sibling tab just broadcast design-changed for our doc
    sync.handleLibraryEvent({ type: 'file-changed', path: '/ws/open.nadoc', file_type: 'part' })
    expect(deps.api.getLibraryFileContent).not.toHaveBeenCalled()
    expect(sync.getReloadingFromSSE()).toBe(false)
  })
})
