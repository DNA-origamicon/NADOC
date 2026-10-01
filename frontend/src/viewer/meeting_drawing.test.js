import { it, expect, vi } from 'vitest'
import { mountMeetingDrawing } from './meeting_drawing.js'
it('requires the toggle and Shift, consumes drawing gestures, and clears shared ink on a camera change', async () => {
  vi.useFakeTimers()
  document.body.innerHTML = '<nav></nav><main><canvas></canvas></main>'
  const canvas = document.querySelector('canvas'), navigation = vi.fn()
  canvas.addEventListener('pointerdown', navigation)
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 500 })
  let camera = { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55 }
  const request = vi.fn(async () => ({ ok: true })), current = {}
  const api = mountMeetingDrawing({ parent: document.querySelector('nav'), canvas, selfId: 'self', viewer: { current, captureCamera: () => camera }, base: '/meeting/r', getRevision: () => 'r', ready: () => true, fetch: request })
  const pointer = (shiftKey, type = 'pointerdown') => { const event = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientX: 500, clientY: 250, shiftKey }); Object.defineProperty(event, 'pointerId', { value: 1 }); canvas.dispatchEvent(event) }
  try {
    pointer(true); expect(navigation).toHaveBeenCalledOnce()
    document.querySelector('[data-draw]').click()
    pointer(false); expect(navigation).toHaveBeenCalledTimes(2)
    pointer(true); expect(navigation).toHaveBeenCalledTimes(2)
    // Separate quick clicks remain separate local marks while an upload is pending.
    pointer(true, 'pointerup'); pointer(true); pointer(true, 'pointerup'); pointer(true)
    expect(document.querySelectorAll('polyline')).toHaveLength(3)
    await vi.advanceTimersByTimeAsync(100)
    expect(JSON.parse(request.mock.calls[0][1].body).points).toEqual([[0, 0]])
    camera = { ...camera, position: [0, 0, 25] }
    await vi.advanceTimersByTimeAsync(100)
    expect(JSON.parse(request.mock.calls.at(-1)[1].body)).toEqual({ revision: 'r', clear: true })
    expect(document.querySelector('polyline')).toBeNull()
  } finally { api.dispose(); vi.useRealTimers() }
})
