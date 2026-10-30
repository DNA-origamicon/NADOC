import { afterEach, expect, it, vi } from 'vitest'
import { gzipSync } from 'node:zlib'
import { geometryReviewCases } from './geometry_review_catalog.js'

afterEach(() => vi.unstubAllGlobals())
it.each([false, true])('loads identical evidence with static-server gzip=%s', async compressed => {
  const evidence = { read_only: true, current: { atoms: [{ x: 1.25 }] }, controls: {} }
  const json = JSON.stringify(evidence)
  const fetch = vi.fn(async () => new Response(compressed ? gzipSync(json) : json))
  vi.stubGlobal('fetch', fetch)
  const signal = new AbortController().signal
  expect(await geometryReviewCases[0].load({ signal })).toEqual(evidence)
  expect(fetch.mock.calls[0][1].signal).toBe(signal)
})

it('reports unavailable evidence rather than displaying an empty comparison', async () => {
  vi.stubGlobal('fetch', async () => new Response('', { status: 503 }))
  await expect(geometryReviewCases[0].load({})).rejects.toThrow('HTTP 503')
})
