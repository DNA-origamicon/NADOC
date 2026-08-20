import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../state/store.js', () => ({
  store: { getState: () => ({}), setState: vi.fn() },
}))

import {
  enginesStatus, getMdJob, getMdTrajectory, getSystemResources,
  launchNativeVR, listActiveJobs, listLibraryFiles, listSimJobs,
  refreshNativeVRJobs,
} from './client.js'
import { docKey } from '../shared/doc_id.js'

function deferredResponse(payload = { ok: true }) {
  let release
  const wait = new Promise(resolve => { release = resolve })
  return {
    wait,
    release: () => release({
      ok: true, status: 200,
      json: async () => payload,
    }),
  }
}

describe('job JSON GET coalescing', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('shares one in-flight identical GET and releases the key after completion', async () => {
    const first = deferredResponse({ available: true })
    global.fetch = vi.fn(() => first.wait)

    const a = enginesStatus()
    const b = enginesStatus()
    expect(global.fetch).toHaveBeenCalledTimes(1)
    first.release()
    await expect(Promise.all([a, b])).resolves.toEqual([
      { available: true }, { available: true },
    ])

    global.fetch.mockResolvedValueOnce({
      ok: true, status: 200, json: async () => ({ available: false }),
    })
    await expect(enginesStatus()).resolves.toEqual({ available: false })
    expect(global.fetch).toHaveBeenCalledTimes(2)
  })

  it('does not merge different paths', async () => {
    global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }))
    await Promise.all([getMdJob('a'), getMdJob('b')])
    expect(global.fetch).toHaveBeenCalledTimes(2)
  })

  it('does not merge requests with independent abort signals', async () => {
    global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }))
    const a = new AbortController()
    const b = new AbortController()
    await Promise.all([
      getMdTrajectory('a', a.signal),
      getMdTrajectory('a', b.signal),
    ])
    expect(global.fetch).toHaveBeenCalledTimes(2)
  })

  it('coalesces shared active-job and same-device resource probes', async () => {
    const jobs = deferredResponse([])
    const resources = deferredResponse({ cpu_pct: 10 })
    global.fetch = vi.fn(url => url.endsWith('/jobs/active') ? jobs.wait : resources.wait)

    const calls = [
      listActiveJobs(), listActiveJobs(),
      getSystemResources('0'), getSystemResources('0'),
    ]
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2))
    jobs.release()
    resources.release()
    await expect(Promise.all(calls)).resolves.toEqual([
      [], [], { cpu_pct: 10 }, { cpu_pct: 10 },
    ])
  })

  it('coalesces the library and unified simulation lists seen during design load', async () => {
    const library = deferredResponse([])
    const simulations = deferredResponse([])
    global.fetch = vi.fn(url => url.includes('/simulate/jobs') ? simulations.wait : library.wait)
    const calls = [
      listLibraryFiles(), listLibraryFiles(),
      listSimJobs('VoltronCoreArm.nadoc'), listSimJobs('VoltronCoreArm.nadoc'),
    ]
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2))
    library.release()
    simulations.release()
    await expect(Promise.all(calls)).resolves.toEqual([[], [], [], []])
  })

  it('launches native VR with a bounded snapshot from the current design job list', async () => {
    localStorage.setItem(docKey('nadoc:workspace-path'), 'Parts/Bundle.nadoc')
    let launchBody = null
    global.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes('/simulate/jobs')) {
        return { ok: true, status: 200, json: async () => [{
          job_id: 'run-1', engine: 'cando', status: 'completed', created_at: 1,
          design_name: 'Bundle solve', viewable: true,
        }] }
      }
      launchBody = JSON.parse(options.body)
      return { ok: true, status: 200, json: async () => ({ running: true }) }
    })

    await expect(launchNativeVR({ representation: 'full' }))
      .resolves.toEqual({ running: true })
    expect(global.fetch.mock.calls[0][0]).toContain(
      '/simulate/jobs?design_source_path=Parts%2FBundle.nadoc',
    )
    expect(launchBody).toEqual(expect.objectContaining({
      representation: 'full',
      jobs_snapshot_available: true,
      jobs_snapshot_total: 1,
      jobs: [expect.objectContaining({
        job_id: 'run-1', engine: 'cando', status: 'completed',
        label: 'Bundle solve', progress_permille: 1000, viewable: true,
      })],
    }))
  })

  it('publishes successful unified-list refreshes to the native live feed', async () => {
    localStorage.setItem(docKey('nadoc:workspace-path'), 'Parts/Bundle.nadoc')
    let feedbackBody = null
    global.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes('/simulate/jobs')) {
        return { ok: true, status: 200, json: async () => [{
          job_id: 'run-2', engine: 'oxdna', status: 'running', created_at: 2,
          design_name: 'Relax', progress_fraction: 0.25,
        }] }
      }
      feedbackBody = JSON.parse(options.body)
      return { ok: true, status: 200, json: async () => ({
        acknowledged: true, sequence: 7,
      }) }
    })

    await expect(refreshNativeVRJobs()).resolves.toEqual({
      acknowledged: true, sequence: 7,
    })
    expect(global.fetch.mock.calls[1][0]).toBe('/api/vr/jobs-feedback')
    expect(feedbackBody).toEqual({
      jobs_snapshot_total: 1,
      jobs: [expect.objectContaining({
        job_id: 'run-2', engine: 'oxdna', status: 'running',
        progress_permille: 250,
      })],
    })
  })
})
