import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initDesignReadinessController, readinessTarget } from './design_readiness_controller.js'
import { createMockStore } from '../test-helpers/mock_store.js'

const design = id => ({ id, helices: [{ id: 'h' }], strands: [] })
const ready = { available: true, state: 'ready', steps: [] }
function deferred() {
  let resolve, reject
  const promise = new Promise((a, b) => { resolve = a; reject = b })
  return { promise, resolve, reject }
}

describe('readiness document and job refresh', () => {
  let ctrl, store, widget, fetchReport
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    store = createMockStore({ currentDesign: design('a') })
    widget = { setReport: vi.fn(), setLoading: vi.fn(), setError: vi.fn() }
    fetchReport = vi.fn().mockResolvedValue(ready)
  })
  afterEach(() => {
    ctrl?.dispose()
    vi.restoreAllMocks()
    vi.useRealTimers()
  })
  function start(options = {}) {
    ctrl = initDesignReadinessController({ store, widget, fetchReport, debounceMs: 20, pollMs: 1000, ...options })
  }

  it('selects the active document rather than a retained part in assembly mode', () => {
    const part = design('part')
    const assembly = { id: 'asm', instances: [{ id: 'i' }] }
    expect(readinessTarget({ currentDesign: part, assemblyActive: true, currentAssembly: assembly })).toEqual({ document: assembly, assembly: true })
    expect(readinessTarget({ design: part, assemblyActive: true }, 'cadnano')).toEqual({ document: part, assembly: false })
    expect(readinessTarget({ currentDesign: { helices: [], strands: [] } })).toBeNull()
  })

  it('hides for an empty or closed document and does not poll', async () => {
    store.setState({ currentDesign: null })
    start()
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchReport).not.toHaveBeenCalled()
    expect(widget.setReport).toHaveBeenLastCalledWith(null)
  })

  it('refreshes after an edit, decorates the response, and ignores unrelated selection changes', async () => {
    const decorate = vi.fn(report => ({ ...report, decorated: true }))
    start({ decorate })
    expect(widget.setLoading).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(20)
    expect(widget.setReport).toHaveBeenLastCalledWith({ ...ready, decorated: true })
    store.setState({ selection: { ids: ['s'] } })
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(1)
    store.setState({ currentDesign: design('a') })
    expect(widget.setLoading).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(2)
  })

  it('discards an old green response after an edit even if fetch ignores cancellation', async () => {
    const old = deferred(), latest = deferred()
    fetchReport.mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise)
    start()
    await vi.advanceTimersByTimeAsync(20)
    const oldSignal = fetchReport.mock.calls[0][1].signal
    store.setState({ currentDesign: design('b') })
    expect(oldSignal.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(20)
    latest.resolve({ state: 'incomplete', design_id: 'b' })
    await vi.advanceTimersByTimeAsync(0)
    old.resolve(ready)
    await vi.advanceTimersByTimeAsync(0)
    expect(widget.setReport).toHaveBeenCalledTimes(1)
    expect(widget.setReport).toHaveBeenLastCalledWith({ state: 'incomplete', design_id: 'b' })
  })

  it('drops readiness when closing while a check is in flight', async () => {
    const pending = deferred()
    fetchReport.mockReturnValue(pending.promise)
    start()
    await vi.advanceTimersByTimeAsync(20)
    store.setState({ currentDesign: null })
    pending.resolve(ready)
    await vi.advanceTimersByTimeAsync(2000)
    expect(widget.setReport).toHaveBeenLastCalledWith(null)
    expect(fetchReport).toHaveBeenCalledTimes(1)
  })

  it('polls for simulation completion without flashing loading on unchanged designs', async () => {
    start()
    await vi.advanceTimersByTimeAsync(1020)
    expect(fetchReport).toHaveBeenCalledTimes(2)
    expect(widget.setLoading).toHaveBeenCalledTimes(1)
    expect(widget.setReport).toHaveBeenCalledTimes(1) // unchanged polling preserves focus/scroll
    window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed'))
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(3)
  })

  it('shows unavailable on failure and recovers on focus', async () => {
    fetchReport.mockRejectedValueOnce(new Error('Offline'))
    start()
    await vi.advanceTimersByTimeAsync(20)
    expect(widget.setError).toHaveBeenLastCalledWith('Offline')
    window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(20)
    expect(widget.setReport).toHaveBeenLastCalledWith(ready)
  })

  it('pauses checks in a hidden tab and cleans up listeners and timers', async () => {
    start()
    await vi.advanceTimersByTimeAsync(20)
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchReport).toHaveBeenCalledTimes(1)
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(20)
    expect(fetchReport).toHaveBeenCalledTimes(2)
    ctrl.dispose()
    store.setState({ currentDesign: design('b') })
    window.dispatchEvent(new Event('focus'))
    window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed'))
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchReport).toHaveBeenCalledTimes(2)
  })
})

it('clears readiness synchronously on reset and ignores stale requests and wake events until a new design loads', async () => {
  vi.useFakeTimers()
  const pending = deferred()
  const store = createMockStore({ currentDesign: design('old') })
  const widget = { setReport: vi.fn(), setLoading: vi.fn(), setError: vi.fn() }
  const fetchReport = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(ready)
  const ctrl = initDesignReadinessController({ store, widget, fetchReport, debounceMs: 1, pollMs: 10 })
  try {
    await vi.advanceTimersByTimeAsync(1)
    const signal = fetchReport.mock.calls[0][1].signal
    window.dispatchEvent(new Event('nadoc:document-reset'))
    expect(signal.aborted).toBe(true)
    expect(widget.setReport).toHaveBeenLastCalledWith(null)
    window.dispatchEvent(new Event('focus'))
    window.dispatchEvent(new Event('nadoc:sim-jobs-changed'))
    store.setState({ selection: {} })
    pending.resolve(ready)
    await vi.advanceTimersByTimeAsync(100)
    expect(fetchReport).toHaveBeenCalledTimes(1)
    expect(widget.setReport).toHaveBeenLastCalledWith(null)
    store.setState({ currentDesign: null })
    store.setState({ currentDesign: design('new') })
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchReport).toHaveBeenCalledTimes(2)
    expect(widget.setReport).toHaveBeenLastCalledWith(ready)
  } finally { ctrl.dispose(); vi.useRealTimers() }
})

it('pauses readiness on welcome even with retained/replaced design objects and resumes when the editor opens', async () => {
  vi.useFakeTimers()
  document.body.innerHTML = '<div id="welcome-screen"></div>'
  const welcome = document.getElementById('welcome-screen')
  const pending = deferred()
  const store = createMockStore({ currentDesign: design('old') })
  const widget = { setReport: vi.fn(), setLoading: vi.fn(), setError: vi.fn() }
  const fetchReport = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(ready)
  const ctrl = initDesignReadinessController({ store, widget, fetchReport, debounceMs: 1, pollMs: 10 })
  try {
    ctrl.show()
    await vi.advanceTimersByTimeAsync(100)
    expect(fetchReport).not.toHaveBeenCalled()
    welcome.classList.add('hidden')
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchReport).toHaveBeenCalledTimes(1)
    const signal = fetchReport.mock.calls[0][1].signal
    welcome.classList.remove('hidden')
    await vi.advanceTimersByTimeAsync(0)
    expect(signal.aborted).toBe(true)
    store.setState({ currentDesign: design('old') })
    window.dispatchEvent(new Event('focus'))
    ctrl.show()
    pending.resolve(ready)
    await vi.advanceTimersByTimeAsync(100)
    expect(fetchReport).toHaveBeenCalledTimes(1)
    expect(widget.setReport).toHaveBeenLastCalledWith(null)
    welcome.classList.add('hidden')
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchReport).toHaveBeenCalledTimes(2)
    expect(widget.setReport).toHaveBeenLastCalledWith(ready)
  } finally { ctrl.dispose(); document.body.replaceChildren(); vi.useRealTimers() }
})
