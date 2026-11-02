import { afterEach, expect, it, vi } from 'vitest'
import { withClashProgress } from './clash_progress.js'
afterEach(() => vi.useRealTimers())

it('polls measured percentages in the original tab and releases the completed check', async () => {
  vi.useFakeTimers()
  let finish
  const update = vi.fn(), headers = { 'X-NADOC-Doc': 'part-a' }
  const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ stage: 'Checking bonds', percent: 42 }) }))
  const run = vi.fn(() => new Promise(resolve => { finish = resolve }))
  const pending = withClashProgress(headers, run, update, { fetchImpl, pollMs: 10 })
  headers['X-NADOC-Doc'] = 'part-b'
  await vi.advanceTimersByTimeAsync(10)
  expect(fetchImpl.mock.calls[0][1].headers).toEqual({ 'X-NADOC-Doc': 'part-a' })
  expect(fetchImpl.mock.calls[0][0]).toContain(run.mock.calls[0][0])
  expect(update).toHaveBeenLastCalledWith({ stage: 'Checking bonds', percent: 42 })
  finish({ count: 0 })
  expect(await pending).toEqual({ count: 0 })
  expect(fetchImpl).toHaveBeenLastCalledWith(expect.any(String), { method: 'DELETE', headers: { 'X-NADOC-Doc': 'part-a' } })
  await vi.advanceTimersByTimeAsync(100)
  expect(fetchImpl).toHaveBeenCalledTimes(2)
})

it.each(['abort', 'reset'])('cancels calculation and ignores late progress on %s', async kind => {
  vi.useFakeTimers()
  let finish, finishPoll
  const update = vi.fn(), abort = new AbortController()
  const fetchImpl = vi.fn((_url, options) => options.method === 'DELETE'
    ? Promise.resolve({ ok: true }) : new Promise(resolve => { finishPoll = resolve }))
  const run = vi.fn(() => new Promise(resolve => { finish = resolve }))
  const pending = withClashProgress({}, run, update, { signal: abort.signal, fetchImpl, pollMs: 10 })
  await vi.advanceTimersByTimeAsync(10)
  if (kind === 'abort') abort.abort()
  else window.dispatchEvent(new Event('nadoc:document-reset'))
  expect(run.mock.calls[0][1].aborted).toBe(true)
  expect(fetchImpl.mock.calls[0][1].signal.aborted).toBe(true)
  finishPoll({ ok: true, json: async () => ({ percent: 90 }) })
  finish(null)
  await pending
  await vi.advanceTimersByTimeAsync(100)
  expect(update).toHaveBeenCalledTimes(1)
  expect(fetchImpl).toHaveBeenCalledTimes(2)
})

it('survives unavailable polling and releases failed checks', async () => {
  vi.useFakeTimers()
  let finish
  const fetchImpl = vi.fn(async () => { throw new Error('offline') })
  const pending = withClashProgress({}, () => new Promise(resolve => { finish = resolve }), vi.fn(), { fetchImpl, pollMs: 10 })
  await vi.advanceTimersByTimeAsync(10)
  finish(null)
  expect(await pending).toBe(null)
  expect(fetchImpl).toHaveBeenCalledTimes(2)
})
