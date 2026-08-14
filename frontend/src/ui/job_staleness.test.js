import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('./primitives/confirm.js', () => ({ showConfirm: vi.fn() }))
vi.mock('./toast.js', () => ({ showToast: vi.fn(), showPersistentToast: vi.fn() }))
vi.mock('../api/client.js', () => ({ selectLoadout: vi.fn(), lastErrorMessage: () => null }))

import { showConfirm } from './primitives/confirm.js'
import { showToast, showPersistentToast } from './toast.js'
import * as api from '../api/client.js'
import { jobOutOfDate, ensureJobCurrent, restoreSubmittedDesign } from './job_staleness.js'

describe('jobOutOfDate', () => {
  it('reflects the backend flag', () => {
    expect(jobOutOfDate({ out_of_date: true })).toBe(true)
    expect(jobOutOfDate({ out_of_date: false })).toBe(false)
    expect(jobOutOfDate({})).toBe(false)
    expect(jobOutOfDate(null)).toBe(false)
  })
})

describe('ensureJobCurrent', () => {
  let rollFn, refetch
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    rollFn = vi.fn().mockResolvedValue({ return_loadout_id: 'L1', matches_job: true })
    refetch = vi.fn().mockResolvedValue()
  })

  it('proceeds immediately when the job is current (no dialog)', async () => {
    const ok = await ensureJobCurrent({ job: { job_id: 'j', out_of_date: false }, rollFn, refetch, isStale: () => false })
    expect(ok).toBe(true)
    expect(showConfirm).not.toHaveBeenCalled()
    expect(rollFn).not.toHaveBeenCalled()
  })

  it('aborts (no roll) when the user cancels the dialog', async () => {
    showConfirm.mockResolvedValue(false)
    const ok = await ensureJobCurrent({ job: { job_id: 'j', out_of_date: true }, rollFn, refetch, isStale: () => true })
    expect(ok).toBe(false)
    expect(rollFn).not.toHaveBeenCalled()
  })

  it('switches to the protected loadout and proceeds when confirmed', async () => {
    showConfirm.mockResolvedValue(true)
    const ok = await ensureJobCurrent({
      job: { job_id: 'j7', out_of_date: true }, rollFn, refetch, isStale: () => true, actionLabel: 'a production run',
    })
    expect(ok).toBe(true)
    expect(rollFn).toHaveBeenCalledWith('j7')
    expect(refetch).not.toHaveBeenCalled()
    await vi.runAllTimersAsync()
    expect(refetch).toHaveBeenCalledOnce()
    expect(showToast).toHaveBeenCalledWith('Protected simulation loadout selected.', 'info')
    expect(showPersistentToast).not.toHaveBeenCalled()
  })

  it('aborts when the roll did not clear the flag (still stale)', async () => {
    showConfirm.mockResolvedValue(true)
    const ok = await ensureJobCurrent({
      job: { job_id: 'j', out_of_date: true },
      rollFn: vi.fn().mockResolvedValue({ matches_job: false }),
      refetch,
      isStale: () => true,
    })
    expect(ok).toBe(false)
    expect(showPersistentToast).not.toHaveBeenCalled()
  })

  it('aborts when the roll request fails (null response)', async () => {
    showConfirm.mockResolvedValue(true)
    rollFn.mockResolvedValue(null)
    const ok = await ensureJobCurrent({ job: { job_id: 'j', out_of_date: true }, rollFn, refetch, isStale: () => false })
    expect(ok).toBe(false)
  })
})

describe('restoreSubmittedDesign', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  it('offers protected-loadout viewing without changing the running job', async () => {
    showConfirm.mockResolvedValue(true)
    const rollFn = vi.fn().mockResolvedValue({ matches_job: true, return_loadout_id: 'latest' })
    const refetch = vi.fn().mockResolvedValue()
    const ok = await restoreSubmittedDesign({
      job: { job_id: 'remote-1', out_of_date: true, execution_target: 'alpine', status: 'running' },
      rollFn, refetch,
    })
    expect(ok).toBe(true)
    expect(showConfirm).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Restore to submitted design?', confirmLabel: 'View loadout', cancelLabel: 'Cancel',
    }))
    expect(showConfirm.mock.calls[0][0].message).toMatch(/will not be stopped or modified/i)
    expect(rollFn).toHaveBeenCalledWith('remote-1')
    expect(showToast).toHaveBeenCalledWith(
      'Protected simulation loadout selected. Editing returns to your last design loadout.', 'info')
    await vi.runAllTimersAsync()
    expect(refetch).toHaveBeenCalledOnce()
  })

  it('does nothing when cancelled or when the warning is not a design mismatch', async () => {
    const rollFn = vi.fn()
    expect(await restoreSubmittedDesign({ job: { job_id: 'gpu', out_of_date: false }, rollFn })).toBe(false)
    showConfirm.mockResolvedValue(false)
    expect(await restoreSubmittedDesign({ job: { job_id: 'stale', out_of_date: true }, rollFn })).toBe(false)
    expect(rollFn).not.toHaveBeenCalled()
  })
})
