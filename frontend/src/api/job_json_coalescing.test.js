import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../state/store.js', () => ({
  store: { getState: () => ({}), setState: vi.fn() },
}))

import {
  enginesStatus, getMdJob, getMdTrajectory, getSystemResources,
  listActiveJobs, listLibraryFiles, listSimJobs,
} from './client.js'

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
})
