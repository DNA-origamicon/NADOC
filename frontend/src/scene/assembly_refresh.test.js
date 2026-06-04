import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initAssemblyRefresh } from './assembly_refresh.js'

// A controllable promise so a test can hold _refreshAssemblyPartInstance "in
// flight" (the only way to exercise the mid-flight coalescing branch).
function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

function makeDeps(overrides = {}) {
  const clusterPanel = { syncInstanceDesign: vi.fn() }
  const store = createMockStore({
    assemblyActive: true,
    currentAssembly: {
      instances: [
        { id: 'i1', source: { type: 'file', path: 'p.nadoc' } },
        { id: 'i2', source: { type: 'file', path: 'p.nadoc' } },
        { id: 'other', source: { type: 'file', path: 'q.nadoc' } },
      ],
    },
  })
  const deps = {
    store,
    api: {
      getAssembly: vi.fn().mockResolvedValue({}),
      getInstanceDesign: vi.fn().mockResolvedValue({ design: { foo: 1 } }),
    },
    assemblyRenderer: {
      rebuild: vi.fn().mockResolvedValue(undefined),
      rebuildLinkers: vi.fn(),
    },
    assemblyJointRenderer: { rebuild: vi.fn() },
    syncLog: vi.fn(),
    setSyncStatus: vi.fn(),
    syncAssemblyBluntEnds: vi.fn(),
    selfSavedPaths: new Set(),
    getClusterPanel: () => clusterPanel,
    ...overrides,
  }
  return { deps, clusterPanel }
}

describe('initAssemblyRefresh', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('no-ops when assembly is not active', async () => {
    const { deps } = makeDeps()
    deps.store.setState({ assemblyActive: false })
    const r = initAssemblyRefresh(deps)
    r.requestRefresh('i1')
    await vi.advanceTimersByTimeAsync(300)
    expect(deps.api.getAssembly).not.toHaveBeenCalled()
  })

  it('no-ops when no instanceId given', async () => {
    const { deps } = makeDeps()
    const r = initAssemblyRefresh(deps)
    r.requestRefresh(undefined)
    await vi.advanceTimersByTimeAsync(300)
    expect(deps.api.getAssembly).not.toHaveBeenCalled()
  })

  it('collapses a burst of requests into ONE refresh', async () => {
    const { deps } = makeDeps()
    const r = initAssemblyRefresh(deps)
    r.requestRefresh('i1')
    r.requestRefresh('i1')
    r.requestRefresh('i1')
    await vi.advanceTimersByTimeAsync(250)
    expect(deps.api.getAssembly).toHaveBeenCalledTimes(1)
    expect(deps.assemblyRenderer.rebuild).toHaveBeenCalledTimes(1)
  })

  it('last request in the window wins (coalesced id)', async () => {
    const { deps } = makeDeps()
    const r = initAssemblyRefresh(deps)
    r.requestRefresh('i1')
    r.requestRefresh('i2')
    await vi.advanceTimersByTimeAsync(250)
    expect(deps.api.getInstanceDesign).toHaveBeenCalledTimes(1)
    expect(deps.api.getInstanceDesign).toHaveBeenCalledWith('i2')
  })

  it('runs the full rebuild pipeline and syncs every instance sharing the source', async () => {
    const { deps, clusterPanel } = makeDeps()
    const r = initAssemblyRefresh(deps)
    r.requestRefresh('i1', 'broadcast')
    await vi.advanceTimersByTimeAsync(250)
    expect(deps.api.getAssembly).toHaveBeenCalledTimes(1)
    expect(deps.assemblyRenderer.rebuild).toHaveBeenCalledTimes(1)
    expect(deps.assemblyRenderer.rebuildLinkers).toHaveBeenCalledTimes(1)
    expect(deps.syncAssemblyBluntEnds).toHaveBeenCalledTimes(1)
    expect(deps.assemblyJointRenderer.rebuild).toHaveBeenCalledTimes(1)
    // i1 and i2 share path p.nadoc → both synced; 'other' (q.nadoc) is not.
    expect(clusterPanel.syncInstanceDesign).toHaveBeenCalledTimes(2)
    expect(clusterPanel.syncInstanceDesign).toHaveBeenCalledWith('i1', { foo: 1 })
    expect(clusterPanel.syncInstanceDesign).toHaveBeenCalledWith('i2', { foo: 1 })
    expect(deps.selfSavedPaths.has('p.nadoc')).toBe(true)
    expect(deps.setSyncStatus).toHaveBeenLastCalledWith('green', 'part synced')
  })

  it('bails before rebuild when the assembly has no instances', async () => {
    const { deps } = makeDeps()
    deps.store.setState({ currentAssembly: { instances: [] } })
    const r = initAssemblyRefresh(deps)
    r.requestRefresh('i1')
    await vi.advanceTimersByTimeAsync(250)
    expect(deps.api.getAssembly).toHaveBeenCalledTimes(1)
    expect(deps.assemblyRenderer.rebuild).not.toHaveBeenCalled()
  })

  it('queues exactly one follow-up run for a trigger arriving mid-flight', async () => {
    const { deps } = makeDeps()
    const d1 = deferred()
    let calls = 0
    deps.api.getAssembly = vi.fn(() => {
      calls += 1
      return calls === 1 ? d1.promise : Promise.resolve({})
    })
    const r = initAssemblyRefresh(deps)
    r.requestRefresh('i1')
    await vi.advanceTimersByTimeAsync(250)   // first run starts, blocks on getAssembly
    expect(deps.api.getAssembly).toHaveBeenCalledTimes(1)
    r.requestRefresh('i2')                    // arrives while in-flight → pending
    r.requestRefresh('i2')                    // a second mid-flight trigger is absorbed
    d1.resolve({})                            // first run completes
    await vi.advanceTimersByTimeAsync(250)    // follow-up run fires
    expect(deps.api.getAssembly).toHaveBeenCalledTimes(2)
    expect(deps.api.getInstanceDesign).toHaveBeenLastCalledWith('i2')
  })

  it('dispose cancels a pending debounce', async () => {
    const { deps } = makeDeps()
    const r = initAssemblyRefresh(deps)
    r.requestRefresh('i1')
    r.dispose()
    await vi.advanceTimersByTimeAsync(300)
    expect(deps.api.getAssembly).not.toHaveBeenCalled()
  })

  it('flush runs the refresh immediately without waiting for the debounce', async () => {
    const { deps } = makeDeps()
    const r = initAssemblyRefresh(deps)
    r.requestRefresh('i1')
    await r.flush()
    expect(deps.api.getAssembly).toHaveBeenCalledTimes(1)
    expect(deps.assemblyRenderer.rebuild).toHaveBeenCalledTimes(1)
  })

  it('a refresh that throws still clears the in-flight latch (recovers)', async () => {
    const { deps } = makeDeps()
    deps.assemblyRenderer.rebuild = vi.fn().mockRejectedValue(new Error('boom'))
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const r = initAssemblyRefresh(deps)
    r.requestRefresh('i1')
    await vi.advanceTimersByTimeAsync(250)
    expect(warn).toHaveBeenCalled()
    // Latch cleared → a later request still runs.
    deps.assemblyRenderer.rebuild = vi.fn().mockResolvedValue(undefined)
    r.requestRefresh('i1')
    await vi.advanceTimersByTimeAsync(250)
    expect(deps.assemblyRenderer.rebuild).toHaveBeenCalledTimes(1)
    warn.mockRestore()
  })
})
