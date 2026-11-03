import { afterEach, expect, it, vi } from 'vitest'
vi.mock('../ui/op_progress.js', () => ({ showOpProgress: vi.fn(), hideOpProgress: vi.fn(), setOpProgressLabel: vi.fn() }))
vi.mock('../shared/connection_monitor.js', () => ({ notifyRequestSuccess: vi.fn(), notifyRequestFailure: vi.fn(), pokeProbe: vi.fn() }))
import { showOpProgress } from '../ui/op_progress.js'
import { saveDesignToWorkspace, resetRevisionWatermark } from './client.js'
import { store } from '../state/store.js'

afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

it.each([false, true])('keeps manual save progress and background autosave distinct (suppressBusy=%s)', async suppressBusy => {
  vi.useFakeTimers()
  resetRevisionWatermark()
  store.setState({ currentDesign: { id: 'part', helices: [], strands: [] } })
  let complete
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { complete = resolve })))
  const result = saveDesignToWorkspace('part.nadoc', { suppressBusy })
  await vi.advanceTimersByTimeAsync(9000)
  expect(showOpProgress).toHaveBeenCalledTimes(suppressBusy ? 0 : 1)
  const saved = { path: 'part.nadoc', identity_disposition: 'confirmed', design_id: 'part', revision: 1 }
  complete({ ok: true, status: 200, headers: new Headers(), json: async () => saved })
  expect(await result).toEqual(saved)
  await vi.advanceTimersByTimeAsync(500)
})
