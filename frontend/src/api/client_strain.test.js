import { afterEach, expect, it, vi } from 'vitest'
import { getOxdnaStrain } from './client.js'

afterEach(() => vi.unstubAllGlobals())
it.each(['mean', 'peak'])('requests %s strain with metric, alignment and cancellation', async aggregation => {
  const signal = new AbortController().signal
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ready: true }) })))
  await getOxdnaStrain('job', { metric: 'wc', aggregation, align: false, signal })
  expect(fetch.mock.calls[0][0]).toContain(`/strain?align=false&metric=wc&aggregation=${aggregation}`)
  expect(fetch.mock.calls[0][1].signal).toBe(signal)
})
it('rejects unsupported temporal aggregations', () => {
  expect(() => getOxdnaStrain('job', { aggregation: 'sum' })).toThrow('aggregation')
})
