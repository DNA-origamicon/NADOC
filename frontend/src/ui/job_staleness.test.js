import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('./primitives/confirm.js', () => ({ showConfirm: vi.fn() }))
vi.mock('./toast.js', () => ({ showToast: vi.fn(), showPersistentToast: vi.fn() }))
vi.mock('../api/client.js', () => ({ selectLoadout: vi.fn(), lastErrorMessage: () => null }))

import { showConfirm } from './primitives/confirm.js'
import { showPersistentToast } from './toast.js'
import { jobOutOfDate, ensureJobCurrent } from './job_staleness.js'

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
    rollFn = vi.fn().mockResolvedValue({ return_loadout_id: 'L1' })
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

  it('rolls + returns true + offers Return-to-latest when confirmed and the roll clears it', async () => {
    showConfirm.mockResolvedValue(true)
    let stale = true
    refetch.mockImplementation(async () => { stale = false })   // roll cleared the flag
    const ok = await ensureJobCurrent({
      job: { job_id: 'j7', out_of_date: true }, rollFn, refetch, isStale: () => stale, actionLabel: 'a production run',
    })
    expect(ok).toBe(true)
    expect(rollFn).toHaveBeenCalledWith('j7')
    expect(refetch).toHaveBeenCalled()
    expect(showPersistentToast).toHaveBeenCalled()           // Return-to-latest affordance
    const action = showPersistentToast.mock.calls[0][1]?.action
    expect(action?.label).toContain('Return to latest')
  })

  it('aborts when the roll did not clear the flag (still stale)', async () => {
    showConfirm.mockResolvedValue(true)
    const ok = await ensureJobCurrent({
      job: { job_id: 'j', out_of_date: true }, rollFn, refetch, isStale: () => true,
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
