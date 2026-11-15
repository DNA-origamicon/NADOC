import { describe, it, expect, vi, afterEach } from 'vitest'
import { flexProgressView, withFlexProgress, flexDisplayProgress } from './md_flex_progress.js'

afterEach(() => vi.useRealTimers())

describe('measured flexibility progress', () => {
  it('shows completed frames within the named stage', () => {
    expect(flexProgressView({ phase: 'atomistic_average', done: 30, total: 150, elapsed_seconds: 7.8 }))
      .toEqual({ percent: 20, text: 'Averaging atom positions · 20% · 30/150 · 7s elapsed' })
    expect(flexProgressView({ phase: 'atomistic_setup', done: 0, total: 1 }).percent).toBe(0)
  })

  it('stops progress polling when the analysis resolves and ignores late responses', async () => {
    vi.useFakeTimers()
    let finish, finishPoll
    const api = { getMdFlexProgress: vi.fn(() => new Promise(resolve => { finishPoll = resolve })) }
    const progress = vi.fn()
    const pending = withFlexProgress(api, 'J', 'rmsf', () => new Promise(resolve => { finish = resolve }), progress)
    await vi.advanceTimersByTimeAsync(200)
    const signal = api.getMdFlexProgress.mock.calls[0][2]
    finish({ ready: true })
    await pending
    expect(signal.aborted).toBe(true)
    progress.mockClear()
    finishPoll({ active: true, done: 10, total: 20 })
    await vi.advanceTimersByTimeAsync(2000)
    expect(progress).not.toHaveBeenCalled()
    expect(api.getMdFlexProgress).toHaveBeenCalledTimes(1)
  })

  it('cleans up after a failed analysis', async () => {
    vi.useFakeTimers()
    const api = { getMdFlexProgress: vi.fn() }
    await expect(withFlexProgress(api, 'J', 'rmsf', () => Promise.reject(new Error('failed')), vi.fn()))
      .rejects.toThrow('failed')
    await vi.advanceTimersByTimeAsync(1000)
    expect(api.getMdFlexProgress).not.toHaveBeenCalled()
  })
})

it('paints a preliminary map once per revision before the final request completes', async () => {
  vi.useFakeTimers()
  let finish
  const partial = { ready: true, preliminary: true, n_frames: 32 }
  const api = { getMdFlexProgress: vi.fn(async () => ({ active: true, revision: 1, partial })) }
  const paint = vi.fn()
  const result = withFlexProgress(api, 'J', 'rmsf', () => new Promise(r => { finish = r }), null, paint)
  await vi.advanceTimersByTimeAsync(1000)
  expect(paint).toHaveBeenCalledExactlyOnceWith(partial, undefined)
  expect(api.getMdFlexProgress.mock.lastCall[3]).toBe(1)
  finish({ ready: true, n_frames: 100 })
  expect((await result).n_frames).toBe(100)
  await vi.advanceTimersByTimeAsync(1000)
  expect(paint).toHaveBeenCalledTimes(1)
})

it('keeps ensemble progress preliminary after drawing a partial atom model', () => {
  const state = { phase: 'display', complete: true, done: 1, total: 1 }
  expect(flexDisplayProgress(state, { preliminary: true, n_frames: 32,
    coverage: { phase: 'tail_preview', processed_frames: 32, total_frames: 1000 } }))
    .toMatchObject({ phase: 'tail_preview', complete: false, done: 32, total: 1000 })
  expect(flexDisplayProgress(state, { preliminary: false })).toBe(state)
})

it('rejects a previous range snapshot while Apply is replacing its worker', async () => {
  vi.useFakeTimers()
  let finish
  const range = { start: 801, end: 1000, interval: 1 }
  const api = { getMdFlexProgress: vi.fn(async () => ({ active: true, revision: 1,
    frame_range: { start: 1, end: 500, interval: 1 }, partial: { ready: true } })) }
  const paint = vi.fn()
  const pending = withFlexProgress(api, 'J', 'rmsf', () => new Promise(r => { finish = r }), null, paint, range)
  await vi.advanceTimersByTimeAsync(200)
  expect(paint).not.toHaveBeenCalled()
  api.getMdFlexProgress.mockResolvedValue({ active: true, revision: 1, frame_range: range, partial: { ready: true } })
  await vi.advanceTimersByTimeAsync(400)
  expect(paint).toHaveBeenCalledTimes(1)
  finish({ ready: true })
  await pending
})
