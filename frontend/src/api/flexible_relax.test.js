import { afterEach, expect, it, vi } from 'vitest'
import { solveFlexibleSegments } from './client.js'
import { store } from '../state/store.js'

afterEach(() => {
  vi.unstubAllGlobals()
  store.setState({ lastError: null })
})

it('keeps the current design on a no-op and returns global diagnostics', async () => {
  const design = store.getState().currentDesign
  const report = { converged: true, transforms: [], connections: [], max_excess_nm: 0 }
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    unchanged: true, relaxation: report,
  }), { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetch)
  expect(await solveFlexibleSegments('one', 'c1')).toEqual(report)
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ scope: 'one', conn_id: 'c1' })
  expect(store.getState().currentDesign).toBe(design)
})

it('surfaces the server nonconvergence message instead of treating null as success', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    detail: { message: 'Maximum overstretch 4.000 nm. No changes applied.' },
  }), { status: 422, headers: { 'Content-Type': 'application/json' } })))
  await expect(solveFlexibleSegments()).rejects.toThrow('Maximum overstretch 4.000 nm. No changes applied.')
})
