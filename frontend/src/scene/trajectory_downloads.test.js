import { describe, it, expect, vi } from 'vitest'
import { initTrajectoryDownloads } from './trajectory_downloads.js'

const payload = { ready: true, frames: [[1], [2]], n_frames: 2 }

describe('background trajectory downloads', () => {
  it('Play joins an unfinished prefetch and reuses its completed coordinates', async () => {
    let finish
    const fetch = vi.fn(() => new Promise(resolve => { finish = resolve }))
    const cache = initTrajectoryDownloads(fetch)
    const background = cache.get('A', { scope: 'job', stride: 1 })
    const play = cache.get('A', { scope: 'job', stride: 1 })
    expect(fetch).toHaveBeenCalledTimes(1)
    finish(payload)
    expect(await background).toBe(payload)
    expect(await play).toBe(payload)
    expect(await cache.get('A', { scope: 'job', stride: 1 })).toBe(payload)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('separates scope/stride and evicts requests when the active animation changes', async () => {
    const fetch = vi.fn(async () => payload)
    const cache = initTrajectoryDownloads(fetch)
    await cache.get('A', { stride: 1 })
    await cache.get('A', { stride: 2 })
    cache.retain([{ jobId: 'A', stride: 2 }])
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true)
    await cache.get('A', { stride: 2 })
    expect(fetch).toHaveBeenCalledTimes(2)
    await cache.get('A', { stride: 1 })
    expect(fetch).toHaveBeenCalledTimes(3)
  })

  it('retries failed and not-ready requests', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ ready: false }).mockResolvedValue(payload)
    const cache = initTrajectoryDownloads(fetch)
    await expect(cache.get('A')).rejects.toThrow('network')
    await cache.get('A')
    expect(await cache.get('A')).toBe(payload)
    expect(fetch).toHaveBeenCalledTimes(3)
  })
})

it('cancels unfinished downloads while preserving downloaded frames', async () => {
  let signal
  const cache = initTrajectoryDownloads(async (id, opts) => {
    if (id === 'ready') return payload
    signal = opts.signal
    await new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError'))))
  })
  await cache.get('ready')
  const pending = cache.get('loading')
  const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  cache.cancelPending()
  await rejected
  expect(signal.aborted).toBe(true)
  expect(await cache.get('ready')).toBe(payload)
})

it('serializes different resolutions of one job so backend extraction cannot supersede itself', async () => {
  let finish
  const fetch = vi.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValue(payload)
  const cache = initTrajectoryDownloads(fetch)
  const first = cache.get('A', { stride: 1 })
  const second = cache.get('A', { stride: 2 })
  expect(fetch).toHaveBeenCalledTimes(1)
  finish(payload)
  await Promise.all([first, second])
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(fetch.mock.calls[1][1].stride).toBe(2)
})
