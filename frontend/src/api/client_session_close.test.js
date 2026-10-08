import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { closeSession, getDesign, getGeometry, getStraightGeometry, importDesign } from './client.js'
import { store } from '../state/store.js'
import { docHeaders } from '../shared/doc_id.js'
import { buildOpProgressReport } from '../ui/op_progress.js'
import { activeOperationTiming, finishOperationTiming } from '../perf/operation_timing.js'
import { clearProcessLog, processLogSnapshot } from '../perf/process_log.js'

vi.mock('../shared/connection_monitor.js', () => ({
  notifyRequestSuccess: vi.fn(), notifyRequestFailure: vi.fn(), pokeProbe: vi.fn(),
}))
import { notifyRequestFailure } from '../shared/connection_monitor.js'
const response = payload => ({ ok: true, status: 200, headers: new Headers(), json: async () => payload })
const reset = () => window.dispatchEvent(new Event('nadoc:document-reset'))
beforeEach(() => {
  vi.useFakeTimers()
  document.body.innerHTML = '<div id="op-progress"></div>'
  clearProcessLog()
  store.setState({ currentDesign: { id: 'old' }, currentGeometry: null, straightGeometry: null, lastError: null })
})
afterEach(() => {
  reset()
  while (activeOperationTiming()) finishOperationTiming(activeOperationTiming(), { status: 'Superseded' })
  document.body.replaceChildren()
  vi.clearAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers()
})
it('closes the active document, aborts geometry immediately and clears its working popup without reporting a disconnect', async () => {
  let signal
  const fetch = vi.fn((url, opts) => {
    if (opts.method === 'DELETE') return Promise.resolve(response({}))
    signal = opts.signal
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason)))
  })
  vi.stubGlobal('fetch', fetch)
  const pending = getGeometry()
  await vi.advanceTimersByTimeAsync(5001)
  expect(buildOpProgressReport()).toContain('Loading Design Geometry')
  await closeSession()
  expect(signal.aborted).toBe(true)
  expect(await pending).toBeNull()
  expect(fetch).toHaveBeenLastCalledWith('/api/design', { method: 'DELETE', headers: docHeaders() })
  expect(docHeaders()['X-NADOC-Doc']).toBeTruthy()
  expect(buildOpProgressReport()).toContain('Active operations: 0')
  expect(activeOperationTiming()).toBeNull()
  expect(processLogSnapshot().entries.find(entry => entry.kind === 'API request')?.status).toBe('Cancelled')
  expect(notifyRequestFailure).not.toHaveBeenCalled()
})
it.each([['geometry', getGeometry], ['straight geometry', getStraightGeometry], ['design', getDesign], ['import', () => importDesign('old')]])('discards late %s after reset even if transport ignores abort', async (_, read) => {
  let resolve, signal
  vi.stubGlobal('fetch', vi.fn((url, opts) => { signal = opts.signal; return new Promise(r => { resolve = r }) }))
  const pending = read()
  await vi.advanceTimersByTimeAsync(0)
  reset()
  expect(signal.aborted).toBe(_ !== 'import') // mutations may finish; only reads abort
  store.setState({ currentDesign: { id: 'new' } })
  resolve(response({ design: { id: 'old' }, nucleotides: [{ helix_id: 'old' }], helix_axes: [], revision: 100 }))
  expect(await pending).toBeNull()
  expect(store.getState().currentDesign.id).toBe('new')
  expect(store.getState().currentGeometry).toBeNull()
  expect(store.getState().straightGeometry).toBeNull()
  expect(notifyRequestFailure).not.toHaveBeenCalled()
  expect(activeOperationTiming()).toBeNull()
})
it('does not fetch chained geometry while the empty welcome screen is showing; new designs still load', async () => {
  document.body.innerHTML = '<div id="welcome-screen"></div>'
  store.setState({ currentDesign: null })
  const fetch = vi.fn(async () => response({ nucleotides: [], helix_axes: [] }))
  vi.stubGlobal('fetch', fetch)
  await getGeometry(); await getStraightGeometry()
  expect(fetch).not.toHaveBeenCalled()
  store.setState({ currentDesign: { id: 'new' } })
  await getGeometry()
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(store.getState().currentGeometry).toEqual([])
})
