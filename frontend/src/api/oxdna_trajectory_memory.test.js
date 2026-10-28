import { afterEach, expect, it, vi } from 'vitest'
vi.mock('../state/store.js', () => ({ store: { getState: () => ({}), setState: vi.fn() } }))
import { getOxdnaTrajectory, getOxdnaTrajectoryBin } from './client.js'
afterEach(() => vi.unstubAllGlobals())

it.each([getOxdnaTrajectory, getOxdnaTrajectoryBin])('rejects oversized downloads before allocating their declared body', async fetchTrajectory => {
  const cancel = vi.fn(), getReader = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200,
    headers: { get: () => String(129 * 1024 * 1024) }, body: { cancel, getReader } })))
  await expect(fetchTrajectory('huge', { align: false, scope: 'job' })).rejects.toThrow('memory limit')
  expect(cancel).toHaveBeenCalledOnce()
  expect(getReader).not.toHaveBeenCalled()
})

it.each([getOxdnaTrajectory, getOxdnaTrajectoryBin])('surfaces the server memory rejection without retrying a larger fallback', async fetchTrajectory => {
  const fetch = vi.fn(async () => ({ ok: false, status: 413, json: async () => ({ detail: 'Not enough safe memory' }) }))
  vi.stubGlobal('fetch', fetch)
  await expect(fetchTrajectory('huge', { scope: 'job' })).rejects.toThrow('Not enough safe memory')
  expect(fetch).toHaveBeenCalledOnce()
})

it('sends sparse preview intervals to the compact trajectory endpoint', async () => {
  const fetch = vi.fn(async () => ({ ok: true, status: 204, arrayBuffer: async () => new ArrayBuffer(0) }))
  vi.stubGlobal('fetch', fetch)
  await getOxdnaTrajectoryBin('preview', { scope: 'job', stride: 5, frameStart: 10, frameEnd: 100, frameStep: 30 })
  const url = fetch.mock.calls[0][0]
  expect(url).toContain('frame_start=10&frame_end=100&frame_step=30')
  expect(url).toContain('stride=5')
})
