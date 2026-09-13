import { it, expect, vi, afterEach } from 'vitest'
import { getMdIonPaths } from './client.js'
import { getDocId } from '../shared/doc_id.js'
afterEach(() => vi.unstubAllGlobals())
it('reports backend details instead of returning null and preserves the document header', async () => {
  const fetcher = vi.fn(async () => ({ ok: false, status: 400, json: async () => ({ detail: 'Could not read trajectory' }) }))
  vi.stubGlobal('fetch', fetcher)
  const signal = new AbortController().signal
  await expect(getMdIonPaths('P1', 200, 10000, signal)).rejects.toThrow('Could not read trajectory')
  expect(fetcher.mock.calls[0][0]).toContain('/md/jobs/P1/ion-paths?before=200&after=10000')
  expect(fetcher.mock.calls[0][1]).toMatchObject({ signal, headers: { 'X-NADOC-Doc': getDocId() } })
})
it('propagates cancellation instead of producing a null payload', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new DOMException('Aborted', 'AbortError') }))
  await expect(getMdIonPaths('P1', 10, 200, new AbortController().signal)).rejects.toMatchObject({ name: 'AbortError' })
})
