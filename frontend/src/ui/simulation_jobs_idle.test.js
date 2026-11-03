import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mountIds } from '../test-helpers/factory_dom.js'

vi.mock('../api/client.js')
import * as api from '../api/client.js'
import { initMdJobsPanel } from './md_jobs_panel.js'
import { initOxdnaJobsPanel } from './oxdna_jobs_panel.js'

let listeners, listen
beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  localStorage.clear()
  listeners = []
  const add = window.addEventListener.bind(window)
  listen = vi.spyOn(window, 'addEventListener').mockImplementation((...args) => {
    listeners.push(args)
    add(...args)
  })
  api.getMdTrajectoryMeta.mockResolvedValue({ ready: false })
  api.getMdDisplayMeta.mockResolvedValue({ ready: false })
  api.getMdJobMetrics.mockResolvedValue([])
  api.getMdQueue.mockResolvedValue({ queue: [] })
  api.oxdnaAvailable.mockResolvedValue({ available: false })
})
afterEach(() => {
  for (const args of listeners) window.removeEventListener(...args)
  listen.mockRestore()
  vi.restoreAllMocks()
  vi.clearAllTimers()
  vi.useRealTimers()
  document.body.innerHTML = ''
})

const engines = [
  { name: 'MD', init: initMdJobsPanel, list: () => api.listMdJobs,
    ids: ['md-jobs-panel', 'md-jobs-panel-body', 'md-jobs-show-all'] },
  { name: 'oxDNA', init: initOxdnaJobsPanel, list: () => api.listOxdnaJobs,
    ids: ['oxdna-jobs-panel', 'oxdna-jobs-body', 'oxdna-jobs-show-all'] },
]
const changed = () => window.dispatchEvent(new CustomEvent('nadoc:design-changed'))
const job = path => ({ job_id: 'existing', design_source_path: path, status: 'completed', created_at: 1 })

describe.each(engines)('$name edit-driven job freshness', ({ init, list, ids }) => {
  it('does not discover jobs for an unused, hidden engine on edits', async () => {
    mountIds(ids)
    document.getElementById(ids[0]).hidden = true
    list().mockResolvedValue([])
    init({ getWorkspacePath: () => 'A.nadoc' })
    changed()
    await vi.advanceTimersByTimeAsync(60000)
    expect(list()).not.toHaveBeenCalled()
    expect(api.getMdDisplayMeta).not.toHaveBeenCalled()
  })

  it.each([{ jobs: [] }, { jobs: [job('Other.nadoc')] }])('does not recheck jobs absent from this part: $jobs', async ({ jobs }) => {
    mountIds(ids)
    // Even when the user lists other parts' jobs, editing A cannot change them.
    list().mockResolvedValue(jobs)
    api.getMdJob.mockResolvedValue(jobs[0])
    init({ getWorkspacePath: () => 'A.nadoc' })
    await vi.advanceTimersByTimeAsync(0)
    document.getElementById(ids[2]).checked = true
    list().mockClear()
    changed(); changed(); changed()
    await vi.advanceTimersByTimeAsync(1000)
    expect(list()).not.toHaveBeenCalled()
  })

  it('refreshes existing jobs, skips edits after switching to an empty part, and allows discovery', async () => {
    mountIds(ids)
    let path = 'A.nadoc'
    list().mockResolvedValue([job(path)])
    api.getMdJob.mockResolvedValue(job(path))
    const panel = init({ getWorkspacePath: () => path })
    await vi.advanceTimersByTimeAsync(0)
    list().mockClear()
    changed(); changed(); changed()
    await vi.advanceTimersByTimeAsync(200)
    expect(list()).toHaveBeenCalledTimes(1)

    // A queued freshness update must not become a discovery request for B.
    changed()
    path = 'B.nadoc'
    await vi.advanceTimersByTimeAsync(200)
    expect(list()).toHaveBeenCalledTimes(1)
    list().mockClear()
    changed()
    await vi.advanceTimersByTimeAsync(200)
    expect(list()).not.toHaveBeenCalled()

    list().mockResolvedValue([job(path)])
    await panel.refresh()
    expect(list()).toHaveBeenCalledOnce()
    list().mockClear()
    changed()
    await vi.advanceTimersByTimeAsync(200)
    expect(list()).toHaveBeenCalledOnce()
  })
})

it('does not arm MD prewarm or remote polling timers without any jobs', async () => {
  mountIds(engines[0].ids)
  api.listMdJobs.mockResolvedValue([])
  const interval = vi.spyOn(globalThis, 'setInterval')
  const prewarmLatest = vi.fn()
  initMdJobsPanel({ getWorkspacePath: () => 'A.nadoc', mdDisplayController: { prewarmLatest } })
  await vi.advanceTimersByTimeAsync(60000)
  expect(interval).not.toHaveBeenCalled()
  expect(api.getMdDisplayMeta).not.toHaveBeenCalled()
  expect(prewarmLatest).not.toHaveBeenCalled()
  interval.mockRestore()
})

it('warms a newly discovered local MD job and stops checking once it is removed', async () => {
  mountIds(engines[0].ids)
  api.listMdJobs.mockResolvedValue([])
  const prewarmLatest = vi.fn(), stopPrewarm = vi.fn()
  const panel = initMdJobsPanel({ getWorkspacePath: () => 'A.nadoc', mdDisplayController: { prewarmLatest, stopPrewarm } })
  await vi.advanceTimersByTimeAsync(0)
  api.listMdJobs.mockResolvedValue([job('A.nadoc')])
  api.getMdJob.mockResolvedValue(job('A.nadoc'))
  api.getMdDisplayMeta.mockResolvedValue({ ready: true, config_path: '/owned/job.namd' })
  await panel.refresh()
  await vi.advanceTimersByTimeAsync(0)
  expect(prewarmLatest).toHaveBeenCalledWith('/owned/job.namd', expect.objectContaining({ jobId: 'existing' }))
  prewarmLatest.mockClear()
  await vi.advanceTimersByTimeAsync(30000)
  expect(prewarmLatest).toHaveBeenCalledOnce()

  api.listMdJobs.mockResolvedValue([])
  await panel.refresh()
  expect(stopPrewarm).toHaveBeenCalled()
  api.getMdDisplayMeta.mockClear()
  await vi.advanceTimersByTimeAsync(60000)
  expect(api.getMdDisplayMeta).not.toHaveBeenCalled()
})

it('keeps monitoring when the final remote refresh discovers another active run', async () => {
  mountIds(engines[0].ids)
  const remote = { ...job('A.nadoc'), execution_target: 'alpine', slurm_job_id: '123', status: 'running' }
  api.listMdJobs.mockResolvedValue([remote])
  api.getMdJob.mockResolvedValue(remote)
  initMdJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
  await vi.advanceTimersByTimeAsync(0)
  api.listMdJobs.mockClear()
  api.listMdJobs.mockResolvedValue([{ ...remote, status: 'completed' }])
  await vi.advanceTimersByTimeAsync(20000)
  expect(api.listMdJobs).toHaveBeenCalledOnce()
  api.listMdJobs.mockResolvedValue([remote, { ...remote, job_id: 'new-run' }])
  await vi.advanceTimersByTimeAsync(20000)
  expect(api.listMdJobs).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(20000)
  expect(api.listMdJobs).toHaveBeenCalledTimes(3)
})
