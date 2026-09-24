import { afterEach, expect, it, vi } from 'vitest'
import { waitForPublicHosting } from './hosting_setup.js'
afterEach(() => { vi.useRealTimers() })
it('starts once and automatically waits through DNS and HTTPS checks', async () => {
  vi.useFakeTimers()
  const pending = { publicAccess: { state: 'dns_pending', message: 'Waiting for public DNS' } }
  const ready = { publicAccess: { state: 'ready' }, shares: [] }
  const api = vi.fn().mockResolvedValueOnce(pending).mockResolvedValueOnce(pending).mockResolvedValue(ready)
  const onProgress = vi.fn(), result = waitForPublicHosting({ api, onProgress })
  await vi.advanceTimersByTimeAsync(6000)
  expect(await result).toBe(ready)
  expect(api.mock.calls.map(call => call[0])).toEqual(['start', 'status', 'status'])
  expect(onProgress).toHaveBeenCalledWith('Waiting for public DNS')
})
it('returns immediately when public access is verified', async () => {
  const ready = { publicAccess: { state: 'ready' } }, api = vi.fn().mockResolvedValue(ready)
  expect(await waitForPublicHosting({ api })).toBe(ready); expect(api).toHaveBeenCalledTimes(1)
})
it('surfaces owner sign-in/approval errors without retrying or publishing', async () => {
  const api = vi.fn().mockRejectedValue(new Error('Sign in to Tailscale'))
  await expect(waitForPublicHosting({ api })).rejects.toThrow('Sign in to Tailscale')
  expect(api).toHaveBeenCalledTimes(1)
})
it('bounds waiting without stopping the background host', async () => {
  vi.useFakeTimers()
  const api = vi.fn().mockResolvedValue({ publicAccess: { state: 'dns_pending', message: 'Pending' } })
  const result = expect(waitForPublicHosting({ api, timeoutMs: 3000 })).rejects.toThrow('keep checking in the background')
  await vi.advanceTimersByTimeAsync(3000); await result
  expect(api.mock.calls.some(([path]) => path === 'stop')).toBe(false)
})
it('cancels pending polls when the app is disposed', async () => {
  vi.useFakeTimers()
  const controller = new AbortController(), api = vi.fn().mockResolvedValue({ publicAccess: { state: 'dns_pending', message: 'Pending' } })
  const result = expect(waitForPublicHosting({ api, signal: controller.signal })).rejects.toThrow('Canceled')
  await vi.advanceTimersByTimeAsync(0); controller.abort(new Error('Canceled')); await result
  await vi.advanceTimersByTimeAsync(10000); expect(api).toHaveBeenCalledTimes(1)
})
it('does not publish when hosting stops or loses its verified state', async () => {
  vi.useFakeTimers()
  for (const changed of [{ running: false }, { running: true }]) {
    const api = vi.fn().mockResolvedValueOnce({ publicAccess: { state: 'checking' } }).mockResolvedValue(changed)
    const result = expect(waitForPublicHosting({ api })).rejects.toThrow('Try Create link again')
    await vi.advanceTimersByTimeAsync(3000); await result
  }
})
