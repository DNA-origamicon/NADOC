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

it('draws with one touch while toggled, ignores extra fingers, and yields to a host lock', async () => {
  vi.useFakeTimers()
  document.body.innerHTML = '<nav></nav><main><canvas></canvas></main>'
  const canvas = document.querySelector('canvas'), navigation = vi.fn(), onActive = vi.fn()
  canvas.addEventListener('pointerdown', navigation)
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 500 })
  const camera = { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55 }
  const request = vi.fn(async () => ({ ok: true }))
  const api = mountMeetingDrawing({ parent: document.querySelector('nav'), canvas, selfId: 'phone', viewer: { mobile: true, current: {}, captureCamera: () => camera }, base: '/meeting/r', getRevision: () => 'r', ready: () => true, onActive, fetch: request })
  const pointer = (type, id, x) => {
    const event = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, buttons: type === 'pointerup' ? 0 : 1, clientX: x, clientY: 250 })
    Object.defineProperty(event, 'pointerId', { value: id }); canvas.dispatchEvent(event)
  }
  try {
    document.querySelector('[data-draw]').click()
    expect(onActive).toHaveBeenLastCalledWith(true)
    pointer('pointerdown', 1, 500); pointer('pointerdown', 2, 700)
    pointer('pointermove', 2, 800); pointer('pointermove', 1, 550); pointer('pointerup', 1, 550)
    expect(navigation).not.toHaveBeenCalled()
    expect(JSON.parse(request.mock.calls[0][1].body).points).toEqual([[0, 0], [.1, 0]])
    api.update({ locked: true })
    expect(onActive).toHaveBeenLastCalledWith(false)
    expect(document.querySelector('[data-draw]').disabled).toBe(true)
    expect(document.querySelector('[data-draw]').getAttribute('aria-pressed')).toBe('false')
    expect(document.querySelector('polyline')).toBeNull()
    api.update({ locked: false })
    expect(document.querySelector('[data-draw]').disabled).toBe(false)
    pointer('pointerdown', 3, 500); expect(navigation).toHaveBeenCalledOnce()
  } finally { api.dispose(); vi.useRealTimers() }
})
