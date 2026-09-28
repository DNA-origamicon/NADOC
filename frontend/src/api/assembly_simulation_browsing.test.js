import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { store } from '../state/store.js'
import * as api from './client.js'

beforeEach(() => {
  store.setState({ assemblyActive: true, currentAssembly: { id: 'browse', instances: [] }, currentDesign: null })
  vi.stubGlobal('fetch', vi.fn(async (url, options) => {
    if (options.method === 'GET') expect(options.body).toBeUndefined()
    if (url.includes('/flatten/')) throw new Error('Browsing must not flatten')
    return new Response(JSON.stringify(url.includes('/jobs') ? [] : { available: true }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }))
})
afterEach(() => {
  store.setState({ assemblyActive: false, currentAssembly: null })
  vi.unstubAllGlobals()
})

it('uses both lightweight transports without preparing an assembly', async () => {
  await Promise.all([api.oxdnaAvailable(), api.namdAvailable(), api.listMdJobs(),
    api.listSimJobs(null, false, { waitForIdle: false }), api.simulateRecommendation()])
  const paths = fetch.mock.calls.map(([url]) => url)
  expect(paths.some(p => p.includes('/simulate/jobs?assembly=true'))).toBe(true)
  expect(paths.some(p => p.includes('/simulate/recommendation?devices=0&assembly=true'))).toBe(true)
  expect(store.getState().currentDesign).toBeNull()
})

it('does not continue to a job launch after preparation fails', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Missing assembly source' }), {
    status: 400, headers: { 'Content-Type': 'application/json' },
  })))
  await expect(api.createCandoJob({ autostart: false })).rejects.toThrow('Missing assembly source')
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0][0]).toContain('/assembly/flatten/load-as-design')
})

it('launches FEM jobs without replacing the assembly scene or fetching part geometry', async () => {
  const original = { id: 'part-still-in-store' }
  store.setState({ currentDesign: original, currentAssembly: { id: 'compact-launch' } })
  vi.stubGlobal('fetch', vi.fn(async url => new Response(JSON.stringify(
    url.includes('/flatten/') ? { design_id: 'flat_compact-launch' } : { job_id: 'prepared' },
  ), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  await api.createCandoJob({ autostart: false })
  await api.createSnupiJob({ autostart: false })
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    expect.stringContaining('/flatten/load-as-design?simulation_only=true'),
    expect.stringContaining('/cando/jobs'), expect.stringContaining('/snupi/jobs'),
  ])
  expect(store.getState().currentDesign).toBe(original)
})
