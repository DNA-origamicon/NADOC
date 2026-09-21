import { it, expect, vi, afterEach } from 'vitest'
import { mountMeetingPresentation } from './meeting_presentation.js'
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })
function setup(role = 'guest') {
  document.body.innerHTML = '<header></header><main><canvas></canvas></main><button id="reset"></button><select id="mode"></select>'
  const events = new EventTarget(); events.close = vi.fn()
  const frames = new Set(), viewer = { current: {}, performanceApi: { busy: false }, runtime: { controls: { enabled: true }, addFrameCallback: fn => frames.add(fn), removeFrameCallback: fn => frames.delete(fn) }, captureCamera: vi.fn(() => ({ position: [2, 3, 4] })), applyCamera: vi.fn() }
  let tick
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
  const dispose = mountMeetingPresentation({ viewer, base: '/meeting/room', role, revision: 'rev', room: 'room', document, fetch: request, eventSource: () => events, setInterval: fn => { tick = fn; return 1 }, clearInterval: vi.fn() })
  const state = (sequence, camera = { position: [10, 0, 30] }, extra = {}) => events.dispatchEvent(new MessageEvent('state', { data: JSON.stringify({ room: 'room', revision: 'rev', sequence, camera, presenting: true, ...extra }) }))
  events.dispatchEvent(new Event('open'))
  return { events, viewer, request, state, tick, dispose, frame: () => [...frames].forEach(fn => fn()) }
}
it('leaves camera independent until Jump or Follow; direct input exits Follow', () => {
  const v = setup(); v.state(1); v.frame(); expect(v.viewer.applyCamera).not.toHaveBeenCalled()
  document.querySelector('[data-jump]').click(); expect(v.viewer.applyCamera).toHaveBeenCalledTimes(1)
  v.state(2); v.frame(); expect(v.viewer.applyCamera).toHaveBeenCalledTimes(1)
  document.querySelector('[data-follow]').click(); v.frame(); expect(v.viewer.applyCamera).toHaveBeenCalledTimes(3)
  document.querySelector('canvas').dispatchEvent(new Event('pointerdown'))
  expect(document.querySelector('[data-follow]').getAttribute('aria-pressed')).toBe('false')
  expect(v.viewer.runtime.controls.enabled).toBe(true)
  v.frame(); expect(v.viewer.applyCamera).toHaveBeenCalledTimes(3); v.dispose()
})
it('ignores stale/cross-snapshot events and releases controls on loss or disposal', () => {
  const v = setup(); v.state(3); document.querySelector('[data-follow]').click()
  v.state(2, { position: [90, 0, 0] }); v.state(4, null, { revision: 'other' }); v.frame()
  expect(v.viewer.applyCamera.mock.calls.at(-1)[0].position).toEqual([10, 0, 30])
  v.events.dispatchEvent(new Event('error')); expect(v.viewer.runtime.controls.enabled).toBe(true)
  v.events.dispatchEvent(new Event('open')); v.state(5); v.frame()
  expect(v.viewer.applyCamera).toHaveBeenCalledTimes(2) // never auto-follow on reconnect
  v.dispose(); expect(v.events.close).toHaveBeenCalledOnce(); expect(document.querySelector('[data-presentation]')).toBeNull()
})
it('coalesces presenter changes with at most one request in flight and pauses explicitly', async () => {
  const v = setup('presenter'); document.querySelector('[data-broadcast]').click()
  await vi.waitFor(() => expect(v.request).toHaveBeenCalledOnce())
  await v.tick(); expect(v.request).toHaveBeenCalledOnce()
  v.viewer.captureCamera.mockReturnValue({ position: [5, 6, 7] })
  await v.tick(); expect(v.request).toHaveBeenCalledTimes(2)
  expect(JSON.parse(v.request.mock.calls[1][1].body).revision).toBe('rev')
  document.querySelector('[data-broadcast]').click()
  await vi.waitFor(() => expect(v.request.mock.calls.at(-1)[0]).toBe('/meeting/room/pause'))
  v.dispose()
})
it('explicit browser offline releases the camera and reconnect never re-enables Follow', () => {
  const v = setup(); v.state(1); document.querySelector('[data-follow]').click()
  window.dispatchEvent(new Event('offline'))
  expect(v.viewer.runtime.controls.enabled).toBe(true)
  expect(document.querySelector('[data-follow]').disabled).toBe(true)
  window.dispatchEvent(new Event('online')); v.events.dispatchEvent(new Event('open')); v.state(2)
  expect(document.querySelector('[data-follow]').disabled).toBe(false)
  expect(document.querySelector('[data-follow]').getAttribute('aria-pressed')).toBe('false')
  v.dispose()
})
