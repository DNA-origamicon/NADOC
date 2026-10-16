import { afterEach, expect, it, vi } from 'vitest'
import { getAllConnectorFrames } from './client.js'
import { showOpProgress } from '../ui/op_progress.js'

vi.mock('../ui/op_progress.js', () => ({ showOpProgress: vi.fn(), hideOpProgress: vi.fn(), setOpProgressLabel: vi.fn() }))
vi.mock('../shared/connection_monitor.js', () => ({
  notifyRequestSuccess: vi.fn(), notifyRequestFailure: vi.fn(), pokeProbe: vi.fn(),
}))
afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

it('loads background connector frames without opening the blocking busy overlay', async () => {
  vi.useFakeTimers()
  let complete
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { complete = resolve })))
  const result = getAllConnectorFrames()
  await vi.advanceTimersByTimeAsync(5001)
  expect(showOpProgress).not.toHaveBeenCalled()
  const frames = { part: { end: { pos: [1, 2, 3], normal: [0, 0, 1] } } }
  complete({ ok: true, status: 200, headers: new Headers(), json: async () => frames })
  expect(await result).toEqual(frames)
  expect(fetch).toHaveBeenCalledWith('/api/assembly/connector-frames', expect.objectContaining({ method: 'GET' }))
})
