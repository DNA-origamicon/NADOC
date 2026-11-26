import {it, expect, vi} from 'vitest'
import {requestOptix, traceExportError} from './path_trace_errors.js'

it.each(['webgl', 'webgpu', 'optix'])('locates module failures for %s without losing the cause', backend => {
  const cause = new TypeError('Failed to fetch dynamically imported module')
  const error = traceExportError(cause, backend, 'loading the renderer')
  expect(error.message).toContain('loading the renderer')
  expect(error.message).toContain('Reload NADOC')
  expect(error.cause).toBe(cause)
})
it('distinguishes unavailable EM data from renderer downloads and preserves cancellation', () => {
  expect(traceExportError(new TypeError('Failed to fetch'), 'webgl', 'preparing EM data').message).toContain('trajectory EM results')
  const abort = new DOMException('Cancelled', 'AbortError')
  expect(traceExportError(abort, 'optix', 'rendering tile 1 of 2')).toBe(abort)
})
it('rejects an oversized encoded body before any network request, counting UTF-8 bytes', async () => {
  const fetcher = vi.fn()
  await expect(requestOptix('/id/frame', {text: 'é'.repeat(20)}, null, {fetcher, maxBytes: 40})).rejects.toThrow(/scene upload.*available RAM\/scratch/)
  expect(fetcher).not.toHaveBeenCalled()
})
it('retains server error details and status', async () => {
  const fetcher = vi.fn(async () => ({ok: false, status: 503, text: async () => '{"detail":"No OptiX device"}'}))
  await expect(requestOptix('/session', {}, null, {fetcher})).rejects.toThrow('OptiX HTTP 503 while starting the native renderer: No OptiX device')
  expect(fetcher).toHaveBeenCalledOnce()
})
it('reports a lost native connection without silently retrying the render', async () => {
  const fetcher = vi.fn(async () => {throw new TypeError('Failed to fetch')})
  await expect(requestOptix('/id/frame', {}, null, {fetcher})).rejects.toThrow(/OptiX connection failed.*rendered frame.*backend is running/)
  expect(fetcher).toHaveBeenCalledOnce()
})
it('returns successful responses and preserves user aborts', async () => {
  const response = {ok: true}, fetcher = vi.fn(async () => response)
  expect(await requestOptix('/session', {}, null, {fetcher})).toBe(response)
  expect(fetcher.mock.calls[0][1].body.type).toBe('application/json')
  const controller = new AbortController(); controller.abort()
  await expect(requestOptix('/session', {}, controller.signal, {fetcher})).rejects.toBe(controller.signal.reason)
  expect(fetcher).toHaveBeenCalledOnce()
})
