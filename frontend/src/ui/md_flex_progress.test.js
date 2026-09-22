import { describe, it, expect, vi, afterEach } from 'vitest'
import { flexProgressView, withFlexProgress } from './md_flex_progress.js'

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
