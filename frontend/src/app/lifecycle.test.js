import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'

// Mock the low-level poller so we can (a) avoid real timers/fetch and (b) capture
// the `onChange` callback the factory registers, then drive it with synthetic
// connection events.
let _capturedOnChange = null
vi.mock('../shared/connection_monitor.js', () => ({
  start: vi.fn(({ onChange } = {}) => { _capturedOnChange = onChange }),
}))

import { initConnectionMonitor } from './lifecycle.js'
import * as connectionMonitor from '../shared/connection_monitor.js'

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
