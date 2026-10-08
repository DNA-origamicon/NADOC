import { afterEach, expect, it, vi } from 'vitest'
import { withGenerationProgress } from './generation_progress.js'
afterEach(() => vi.useRealTimers())
it('polls the fixed document, reports stages, and stops after completion', async () => {
  vi.useFakeTimers()
  let finish
  const update = vi.fn(), headers = { 'X-NADOC-Doc': 'part-a' }
  const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ stage: 'Bends', fraction: .2 }) }))
  const run = vi.fn(() => new Promise(resolve => { finish = resolve }))
  const pending = withGenerationProgress(headers, run, update, { fetchImpl, pollMs: 10 })
  await vi.advanceTimersByTimeAsync(10)
  expect(fetchImpl.mock.calls[0][1].headers).toEqual(headers)
  expect(fetchImpl.mock.calls[0][0]).toContain(run.mock.calls[0][0])
  expect(update).toHaveBeenLastCalledWith({ stage: 'Bends', fraction: .2 })
  finish({ generation: {} })
  await pending
  expect(update).toHaveBeenLastCalledWith(expect.objectContaining({ state: 'complete', fraction: 1 }))
  await vi.advanceTimersByTimeAsync(100)
  expect(fetchImpl).toHaveBeenCalledTimes(1)
})
it('cancels outstanding polling on document reset and does not publish late progress', async () => {
  vi.useFakeTimers()
  let finish, finishPoll
  const update = vi.fn()
  const fetchImpl = vi.fn(() => new Promise(resolve => { finishPoll = resolve }))
  const pending = withGenerationProgress({}, () => new Promise(resolve => { finish = resolve }), update, { fetchImpl, pollMs: 10 })
  await vi.advanceTimersByTimeAsync(10)
  window.dispatchEvent(new Event('nadoc:document-reset'))
  expect(fetchImpl.mock.calls[0][1].signal.aborted).toBe(true)
  finishPoll({ ok: true, json: async () => ({ fraction: .9 }) })
  finish({})
  await pending
  await vi.advanceTimersByTimeAsync(100)
  expect(update).toHaveBeenCalledTimes(1)
  expect(fetchImpl).toHaveBeenCalledTimes(1)
})
