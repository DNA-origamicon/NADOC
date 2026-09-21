import { it, expect, vi, afterEach } from 'vitest'
import { mountPresenterAttendance } from './meeting_attendance.js'
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })
function setup() {
  document.body.innerHTML = '<label class="open" hidden></label><main></main>'
  const shared = {}, frames = new Set(), viewer = { current: shared, runtime: { addFrameCallback: f => frames.add(f), removeFrameCallback: f => frames.delete(f) } }
  const request = vi.fn().mockResolvedValue({ ok: true }), resume = vi.fn().mockImplementation(async () => { viewer.current = shared })
  const stop = vi.fn(), mount = vi.fn(() => stop)
  const dispose = mountPresenterAttendance({ viewer, base: '/meeting/room', document, fetch: request, resume, mount })
  return { viewer, shared, request, resume, mount, stop, dispose, frame: () => [...frames].forEach(f => f()) }
}
it('leaves without ending the room, permits private files, and returns to the original snapshot', async () => {
  const v = setup(); expect(v.mount).toHaveBeenCalledOnce()
  document.querySelector('[data-attendance]').click()
  await vi.waitFor(() => expect(v.request).toHaveBeenCalledOnce())
  expect(v.request.mock.calls[0][0]).toBe('/meeting/room/leave')
  expect(v.stop).toHaveBeenCalledOnce(); expect(document.querySelector('.open').hidden).toBe(false)
  v.viewer.current = {}; v.frame()
  document.querySelector('[data-attendance]').click()
  await vi.waitFor(() => expect(v.mount).toHaveBeenCalledTimes(2))
  expect(v.viewer.current).toBe(v.shared); expect(document.querySelector('.open').hidden).toBe(true)
  v.dispose(); expect(document.querySelector('[data-attendance]')).toBeNull()
})
it('loading another snapshot automatically leaves; failed return remains private and retryable', async () => {
  const v = setup(); v.viewer.current = {}; v.frame()
  await vi.waitFor(() => expect(v.request).toHaveBeenCalledOnce())
  v.resume.mockRejectedValueOnce(new Error('Host unavailable'))
  document.querySelector('[data-attendance]').click()
  await vi.waitFor(() => expect(document.querySelector('[data-attendance-status]').textContent).toContain('Host unavailable'))
  expect(v.mount).toHaveBeenCalledOnce(); expect(document.querySelector('.open').hidden).toBe(false)
  expect(document.querySelector('[data-attendance]').disabled).toBe(false)
  v.dispose()
})
it('recognizes a host-published revision without treating it as a private file', () => {
  const v = setup(), next = {}
  v.mount.mock.calls[0][0].onSharedView(next); v.viewer.current = next; v.frame()
  expect(v.stop).not.toHaveBeenCalled(); expect(v.request).not.toHaveBeenCalled()
  expect(document.querySelector('[data-attendance]').textContent).toBe('Leave presentation')
  v.dispose()
})
