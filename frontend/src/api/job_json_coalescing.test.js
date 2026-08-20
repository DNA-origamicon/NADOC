import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../state/store.js', () => ({
  store: { getState: () => ({}), setState: vi.fn() },
}))

import {
  enginesStatus, getMdJob, getMdTrajectory, getSystemResources,
  launchNativeVR, listActiveJobs, listLibraryFiles, listSimJobs,
  refreshNativeVRJobs, refreshNativeVRVisualization,
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

  it('launches native VR without the archived native job-list fetch', async () => {
    let launchBody = null
    global.fetch = vi.fn(async (_url, options = {}) => {
      launchBody = JSON.parse(options.body)
      return { ok: true, status: 200, json: async () => ({ running: true }) }
    })

    await expect(launchNativeVR({
      representation: 'full', coloring: 'cluster',
      active_job_engine: 'cando', active_job_id: 'run-1',
      visualization_mode: 'namd_display',
      visualization_points: [{ owner_token: 'base-token', position: [1, 2, 3] }],
    }))
      .resolves.toEqual({ running: true })
    expect(global.fetch).toHaveBeenCalledTimes(1)
    expect(global.fetch.mock.calls[0][0]).toBe('/api/vr/launch')
    expect(launchBody).toEqual(expect.objectContaining({
      representation: 'full',
      coloring: 'cluster',
      active_job_engine: null,
      active_job_id: null,
      jobs_snapshot_available: false,
      jobs_snapshot_total: 0,
      jobs: [],
      visualization_mode: 'namd_display',
      visualization_points: [{ owner_token: 'base-token', position: [1, 2, 3] }],
    }))
  })

  it('publishes visualization updates without fetching the archived job list', async () => {
    let body = null
    global.fetch = vi.fn(async (url, options = {}) => {
      body = JSON.parse(options.body)
      return { ok: true, status: 200, json: async () => ({
        acknowledged: true, visualization_sequence: 3,
      }) }
    })
    await expect(refreshNativeVRVisualization({
      visualization_mode: 'oxdna_rmsf',
      visualization_points: [{ owner_token: 'base-token', position: [1, 2, 3], color: 9 }],
    })).resolves.toEqual({ acknowledged: true, visualization_sequence: 3 })
    expect(global.fetch).toHaveBeenCalledTimes(1)
    expect(global.fetch.mock.calls[0][0]).toBe('/api/vr/visualization-feedback')
    expect(body).toEqual({
      visualization_mode: 'oxdna_rmsf',
      visualization_points: [{ owner_token: 'base-token', position: [1, 2, 3], color: 9 }],
    })
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

    await expect(refreshNativeVRJobs({
      active_job_engine: 'oxdna', active_job_id: 'run-2',
      representation: 'stick', coloring: 'base',
      visualization_mode: 'oxdna_rmsf',
      visualization_points: [{ owner_token: 'base-token', position: [1, 2, 3], color: 0x123456 }],
    })).resolves.toEqual({
      acknowledged: true, sequence: 7,
    })
    expect(global.fetch.mock.calls[1][0]).toBe('/api/vr/jobs-feedback')
    expect(feedbackBody).toEqual({
      jobs_snapshot_total: 1,
      active_job_engine: 'oxdna',
      active_job_id: 'run-2',
      representation: 'stick',
      coloring: 'base',
      visualization_mode: 'oxdna_rmsf',
      visualization_points: [{ owner_token: 'base-token', position: [1, 2, 3], color: 0x123456 }],
      jobs: [expect.objectContaining({
        job_id: 'run-2', engine: 'oxdna', status: 'running',
        progress_permille: 250,
      })],
    })
  })
})
