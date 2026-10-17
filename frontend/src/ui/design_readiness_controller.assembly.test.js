import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initDesignReadinessController } from './design_readiness_controller.js'
import { createMockStore } from '../test-helpers/mock_store.js'

const ready = { available: true, state: 'ready', steps: [] }
function sourceVersion(instance, version = 'f:/part.nadoc:1:') {
  Object.defineProperty(instance, 'geometrySourceKey', { value: version, configurable: true })
  return instance
}
function assembly() {
  return { id: 'assembly', joints: [], instances: [sourceVersion({
    id: 'a', representation: 'cylinders', source: { type: 'file', path: 'part.nadoc' },
    transform: { translation: [0, 0, 0] },
  })] }
}
function withRepresentation(current, representation) {
  const next = JSON.parse(JSON.stringify(current))
  next.instances.forEach((instance, index) => {
    instance.representation = representation
    if (current.instances[index].geometrySourceKey !== undefined)
      sourceVersion(instance, current.instances[index].geometrySourceKey)
  })
  return next
}
function deferred() {
  let resolve, reject
  const promise = new Promise((a, b) => { resolve = a; reject = b })
  return { promise, resolve, reject }
}

describe('readiness continuity across assembly display changes', () => {
  let controller, store, widget, fetchReport, onReport
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    store = createMockStore({ assemblyActive: true, currentAssembly: assembly() })
    widget = { setReport: vi.fn(), setLoading: vi.fn(), setError: vi.fn() }
    fetchReport = vi.fn().mockResolvedValue(ready)
    onReport = vi.fn()
  })
  afterEach(() => {
    controller?.dispose()
    vi.restoreAllMocks()
    vi.useRealTimers()
  })
  const start = () => {
    controller = initDesignReadinessController({ store, widget, fetchReport, onReport, debounceMs: 20 })
  }

  it('retains one pending check and accepts its result after optimistic choices and authoritative acknowledgements', async () => {
    const pending = deferred()
    fetchReport.mockReturnValueOnce(pending.promise)
    start()
    await vi.advanceTimersByTimeAsync(20)
    const signal = fetchReport.mock.calls[0][1].signal
    for (const representation of ['full', 'beads', 'cylinders', 'full']) {
      const next = withRepresentation(store.getState().currentAssembly, representation)
      store.setState({ currentAssembly: next })
      await vi.advanceTimersByTimeAsync(30)
      // A second, separately decoded acknowledgement has the same semantics.
      store.setState({ currentAssembly: withRepresentation(next, representation) })
    }
    expect(signal.aborted).toBe(false)
    expect(fetchReport).toHaveBeenCalledOnce()
    expect(widget.setLoading).toHaveBeenCalledOnce()
    pending.resolve(ready)
    await vi.advanceTimersByTimeAsync(0)
    expect(widget.setReport).toHaveBeenLastCalledWith(ready)
    expect(onReport).toHaveBeenCalledWith(ready)
  })

  it('retains the report across display edits and continues normal source-file/job polling with the latest snapshot', async () => {
    start()
    await vi.advanceTimersByTimeAsync(20)
    const next = withRepresentation(store.getState().currentAssembly, 'beads')
    store.setState({ currentAssembly: next })
    expect(controller.getReport()).toBe(ready)
    await vi.advanceTimersByTimeAsync(9999)
    expect(fetchReport).toHaveBeenCalledOnce()
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchReport).toHaveBeenCalledTimes(2)
    expect(fetchReport.mock.calls[1][0].document).toBe(next)
    expect(widget.setLoading).toHaveBeenCalledOnce()
    window.dispatchEvent(new Event('nadoc:sim-jobs-changed'))
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(3)
    controller.refresh()
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(4)
  })

  it.each(['version', 'pose', 'topology', 'visibility'])('rejects a stale response after a real %s change', async change => {
    const pending = deferred()
    fetchReport.mockReturnValueOnce(pending.promise).mockResolvedValue({ ...ready, state: 'incomplete' })
    start()
    await vi.advanceTimersByTimeAsync(20)
    const signal = fetchReport.mock.calls[0][1].signal
    const next = withRepresentation(store.getState().currentAssembly, 'full')
    if (change === 'version') sourceVersion(next.instances[0], 'f:/part.nadoc:2:')
    if (change === 'pose') next.instances[0].transform.translation[0] = 10
    if (change === 'topology') next.assembly_strands = [{ id: 'new' }]
    if (change === 'visibility') next.instances[0].visible = false
    store.setState({ currentAssembly: next })
    expect(signal.aborted).toBe(true)
    expect(controller.getReport()).toBeNull()
    await vi.advanceTimersByTimeAsync(20)
    pending.resolve(ready) // fetch deliberately ignores its aborted signal
    await vi.advanceTimersByTimeAsync(0)
    expect(widget.setReport).toHaveBeenCalledOnce()
    expect(controller.getReport().state).toBe('incomplete')
  })

  it('captures old values before same-object representation, pose, and nested inline-source mutations', async () => {
    const pending = deferred()
    fetchReport.mockReturnValueOnce(pending.promise)
    const same = store.getState().currentAssembly
    same.instances[0].source = { type: 'inline', design: { id: 'part', helices: [{ length_bp: 10 }] } }
    start()
    await vi.advanceTimersByTimeAsync(20)
    const signal = fetchReport.mock.calls[0][1].signal
    same.instances[0].representation = 'full'
    store.setState({ selection: 'a' })
    expect(signal.aborted).toBe(false)
    same.instances[0].transform.translation[0] = 5
    store.setState({ selection: 'b' })
    expect(signal.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(2)
    same.instances[0].source.design.helices[0].length_bp = 20
    store.setState({ selection: 'a' })
    expect(controller.getReport()).toBeNull()
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(3)
    pending.resolve({ ...ready, obsolete: true })
    await vi.advanceTimersByTimeAsync(0)
    expect(controller.getReport()).toBe(ready)
  })

  it('rechecks fresh unversioned snapshots while leaving same-object display and selection updates alone', async () => {
    delete store.getState().currentAssembly.instances[0].geometrySourceKey
    start()
    await vi.advanceTimersByTimeAsync(20)
    store.getState().currentAssembly.instances[0].representation = 'full'
    store.setState({ selection: 'a' })
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledOnce()
    store.setState({ currentAssembly: withRepresentation(store.getState().currentAssembly, 'beads') })
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(2)
  })

  it('retargets a pending inline-source wait when a fresh equal snapshot changes representation', async () => {
    const pending = deferred()
    fetchReport.mockReturnValueOnce(pending.promise)
    store.getState().currentAssembly.instances[0].source = { type: 'inline', design: { id: 'part', helices: [] } }
    start()
    await vi.advanceTimersByTimeAsync(20)
    const oldSignal = fetchReport.mock.calls[0][1].signal
    const latest = withRepresentation(store.getState().currentAssembly, 'full')
    store.setState({ currentAssembly: latest })
    expect(oldSignal.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(2)
    expect(fetchReport.mock.calls[1][0].document).toBe(latest)
    pending.resolve({ ...ready, obsolete: true })
    await vi.advanceTimersByTimeAsync(0)
    expect(controller.getReport()).toBe(ready)
  })

  it('preserves error retries and explicit job refresh after representation reuse', async () => {
    fetchReport.mockRejectedValueOnce(new Error('Offline'))
    start()
    await vi.advanceTimersByTimeAsync(20)
    expect(widget.setError).toHaveBeenCalledWith('Offline')
    store.setState({ currentAssembly: withRepresentation(store.getState().currentAssembly, 'beads') })
    await vi.advanceTimersByTimeAsync(10000)
    expect(fetchReport).toHaveBeenCalledTimes(2)
    expect(controller.getReport()).toBe(ready)
    window.dispatchEvent(new Event('nadoc:sim-jobs-changed'))
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(3)
  })

  it('retires pending work on reset even when the replacement document has identical authored inputs', async () => {
    const pending = deferred()
    fetchReport.mockReturnValueOnce(pending.promise)
    start()
    await vi.advanceTimersByTimeAsync(20)
    const signal = fetchReport.mock.calls[0][1].signal
    window.dispatchEvent(new Event('nadoc:document-reset'))
    expect(signal.aborted).toBe(true)
    expect(widget.setReport).toHaveBeenLastCalledWith(null)
    store.setState({ currentAssembly: withRepresentation(store.getState().currentAssembly, 'full') })
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(2)
    pending.resolve({ ...ready, obsolete: true })
    await vi.advanceTimersByTimeAsync(0)
    expect(controller.getReport()).toBe(ready)
  })
})
