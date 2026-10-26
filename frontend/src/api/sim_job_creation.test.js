import { beforeEach, expect, it, vi } from 'vitest'
import { mergeCreatingJobs, withCreatingJob } from './sim_job_creation.js'

beforeEach(() => window.dispatchEvent(new Event('nadoc:document-reset')))

it('publishes a selected-row candidate synchronously and retains it across stale lists', async () => {
  const events = []
  const listener = e => events.push(e.detail)
  window.addEventListener('nadoc:sim-job-creation', listener)
  let resolve
  const request = withCreatingJob('namd', { execution_target: 'alpine' },
    () => new Promise(r => { resolve = r }))
  const pending = events[0].node
  expect(pending).toMatchObject({ creating: true, status: 'preparing', execution_target: 'alpine' })
  expect(mergeCreatingJobs([], 'namd')).toEqual([pending])
  const job = { job_id: 'saved', status: 'queued' }
  resolve({ job })
  await request
  expect(events[1]).toMatchObject({ removeJobId: pending.job_id, node: { ...job, engine: 'namd' } })
  expect(mergeCreatingJobs([], 'namd')).toEqual([{ ...job, engine: 'namd' }])
  expect(mergeCreatingJobs([job], 'namd')).toEqual([job])
  expect(mergeCreatingJobs([], 'namd')).toEqual([])
  window.removeEventListener('nadoc:sim-job-creation', listener)
})

it.each(['null', 'throw'])('removes the pending row on %s failure', async failure => {
  const listener = vi.fn()
  window.addEventListener('nadoc:sim-job-creation', listener)
  const request = withCreatingJob('oxdna', {}, async () => {
    if (failure === 'throw') throw new Error('offline')
    return null
  })
  if (failure === 'throw') await expect(request).rejects.toThrow('offline')
  else await request
  expect(listener.mock.calls.at(-1)[0].detail.node).toBeNull()
  expect(mergeCreatingJobs([], 'oxdna')).toEqual([])
  window.removeEventListener('nadoc:sim-job-creation', listener)
})

it('ignores completion after the document changes', async () => {
  let resolve
  const request = withCreatingJob('namd', {}, () => new Promise(r => { resolve = r }))
  window.dispatchEvent(new Event('nadoc:document-reset'))
  const listener = vi.fn()
  window.addEventListener('nadoc:sim-job-creation', listener)
  resolve({ job_id: 'old-document-job' })
  await request
  expect(listener).not.toHaveBeenCalled()
  expect(mergeCreatingJobs([], 'namd')).toEqual([])
  window.removeEventListener('nadoc:sim-job-creation', listener)
})
