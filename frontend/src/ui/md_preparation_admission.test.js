import { describe, it, expect, vi } from 'vitest'
import { admitMdPreparation } from './md_preparation_admission.js'

describe('preparation admission', () => {
  it.each(['local', 'alpine', 'runpod'])('checks preparation for %s', async execution_target => {
    const plan = vi.fn().mockResolvedValue({ ready: true, detail: 'Preparing with adequate RAM' })
    const progress = vi.fn(), notify = vi.fn()
    expect(await admitMdPreparation({ execution_target }, { plan, progress, notify })).toBe(true)
    expect(plan).toHaveBeenCalledWith({ execution_target })
    expect(progress).toHaveBeenCalledWith('Preparing with adequate RAM')
    expect(notify).not.toHaveBeenCalled()
  })
  it.each([null, { ready: false, detail: 'Insufficient capacity' }])('blocks an unadmitted plan', async result => {
    const notify = vi.fn()
    expect(await admitMdPreparation({}, { plan: async () => result, progress: vi.fn(), notify })).toBe(false)
    expect(notify).toHaveBeenCalled()
  })
  it('reports a failed check without launching', async () => {
    const notify = vi.fn()
    expect(await admitMdPreparation({}, { plan: async () => { throw Error('offline') }, progress: vi.fn(), notify })).toBe(false)
    expect(notify).toHaveBeenCalledWith('offline', 'error')
  })
})
