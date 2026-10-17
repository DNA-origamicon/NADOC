import { afterEach, expect, it, vi } from 'vitest'
import { saveAssemblyAs } from './client.js'
import { showOpProgress } from '../ui/op_progress.js'

vi.mock('../ui/op_progress.js', () => ({ showOpProgress: vi.fn(), hideOpProgress: vi.fn(), setOpProgressLabel: vi.fn() }))
vi.mock('../shared/connection_monitor.js', () => ({
  notifyRequestSuccess: vi.fn(), notifyRequestFailure: vi.fn(), pokeProbe: vi.fn(),
}))
afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

it.each([false, true])('keeps manual progress and quiet autosave separate (suppressBusy=%s)', async suppressBusy => {
  vi.useFakeTimers()
  let complete
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { complete = resolve })))
  const result = suppressBusy ? saveAssemblyAs('assembly.nass', true, { suppressBusy }) : saveAssemblyAs('assembly.nass')
  await vi.advanceTimersByTimeAsync(5001)
  expect(showOpProgress).toHaveBeenCalledTimes(suppressBusy ? 0 : 1)
  const saved = { path: 'assembly.nass' }
  complete({ ok: true, status: 200, headers: new Headers(), json: async () => saved })
  expect(await result).toEqual(saved)
  expect(fetch).toHaveBeenCalledWith('/api/assembly/save', expect.objectContaining({
    method: 'POST', body: JSON.stringify({ path: 'assembly.nass', overwrite: true }),
  }))
  await vi.advanceTimersByTimeAsync(500)
})
