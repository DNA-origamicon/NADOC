import { it, expect, vi, afterEach } from 'vitest'
import { getCandoVisualizationBin } from './client.js'
vi.mock('./surface_progress_request.js', () => ({ withSurfaceProgress: (path, headers, fn) => fn(headers) }))
afterEach(() => vi.unstubAllGlobals())
it('rejects excessive declared size before allocating or reading the body', async () => {
  const cancel = vi.fn(), getReader = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true,
    headers: new Headers({ 'x-nadoc-uncompressed-length': String(300 * 1024 * 1024) }), body: { cancel, getReader } })))
  await expect(getCandoVisualizationBin('job', 'flex')).rejects.toThrow('memory limit')
  expect(cancel).toHaveBeenCalledOnce()
  expect(getReader).not.toHaveBeenCalled()
})
it('passes abort and streams compact bytes without requiring a progress callback', async () => {
  const signal = new AbortController().signal
  const read = vi.fn().mockResolvedValueOnce({ done: false, value: new Uint8Array([1,2,3,4]) }).mockResolvedValue({ done: true })
  const fetcher = vi.fn(async () => ({ ok: true, headers: new Headers(), body: { getReader: () => ({ read }) } }))
  vi.stubGlobal('fetch', fetcher)
  expect([...new Uint8Array(await getCandoVisualizationBin('job', 'deform', { signal }))]).toEqual([1,2,3,4])
  expect(fetcher.mock.calls[0][1].signal).toBe(signal)
})
