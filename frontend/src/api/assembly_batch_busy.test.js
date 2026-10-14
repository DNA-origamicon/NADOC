import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { batchPatchInstances } from './client.js'
import { store } from '../state/store.js'
import { showOpProgress } from '../ui/op_progress.js'

vi.mock('../ui/op_progress.js', () => ({ showOpProgress: vi.fn(), hideOpProgress: vi.fn(), setOpProgressLabel: vi.fn() }))
vi.mock('../shared/connection_monitor.js', () => ({
  notifyRequestSuccess: vi.fn(), notifyRequestFailure: vi.fn(), pokeProbe: vi.fn(),
}))

beforeEach(() => {
  vi.useFakeTimers()
  store.setState({ featureSeekPending: false, currentAssembly: { id: 'busy-test', instances: [] } })
})
afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

it.each([true, false, undefined])('forwards suppressBusy=%s while preserving the normal batch response path', async suppressBusy => {
  let complete
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { complete = resolve })))
  const patches = [{ id: 'part', representation: 'full' }]
  const options = suppressBusy === undefined ? undefined : { suppressBusy }
  const result = batchPatchInstances(patches, options)
  await vi.advanceTimersByTimeAsync(5001)
  expect(showOpProgress).toHaveBeenCalledTimes(suppressBusy ? 0 : 1)
  const response = { assembly: { id: 'busy-test', instances: patches }, revision: 1 }
  complete({ ok: true, status: 200, headers: new Headers(), json: async () => response })
  expect(await result).toEqual(response)
  expect(store.getState().currentAssembly).toEqual(response.assembly)
  expect(fetch).toHaveBeenCalledWith('/api/assembly/instances/batch', expect.objectContaining({
    method: 'PATCH', body: JSON.stringify({ patches }),
  }))
})
