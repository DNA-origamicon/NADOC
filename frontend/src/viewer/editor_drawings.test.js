import { it, expect, vi } from 'vitest'
import { initEditorDrawings } from './editor_drawings.js'
it('reads marks only while presenting and removes the overlay when the room ends', async () => {
  vi.useFakeTimers()
  document.body.innerHTML = '<main><canvas></canvas></main>'
  const canvas = document.querySelector('canvas'), pose = { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55 }, scene = {}
  let room = null
  const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ revision: 'r', serverTime: 0, drawings: [{ author: 'guest', id: '1', revision: 'r', camera: pose, points: [[0, 0], [.1, .1]], expiresAt: 2500 }] }) }))
  const api = initEditorDrawings({ prepared: { captureView: () => ({ canvas, pose, scene }) }, getRoom: () => room, fetch })
  try {
    await vi.advanceTimersByTimeAsync(200); expect(fetch).not.toHaveBeenCalled()
    room = { id: 'room' }; await vi.advanceTimersByTimeAsync(200)
    expect(fetch.mock.calls[0][0]).toBe('/__nadoc_share/shares/room/drawings')
    expect(document.querySelector('polyline')).not.toBeNull()
    room = null; await vi.advanceTimersByTimeAsync(200)
    expect(document.querySelector('[data-meeting-drawing]')).toBeNull()
  } finally { api.dispose(); vi.useRealTimers() }
})

it('cancels a pending drawing read before revocation and resumes for a new room', async () => {
  vi.useFakeTimers()
  let room = { id: 'old' }, signal
  const fetch = vi.fn((_url, options) => new Promise((_resolve, reject) => {
    signal = options.signal
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const api = initEditorDrawings({ prepared: {}, getRoom: () => room, fetch })
  try {
    await vi.advanceTimersByTimeAsync(200)
    const oldSignal = signal
    room = null; api.clear()
    expect(oldSignal.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(200)
    expect(fetch).toHaveBeenCalledTimes(1)
    room = { id: 'new' }
    await vi.advanceTimersByTimeAsync(200)
    expect(fetch.mock.calls[1][0]).toContain('/new/drawings')
    expect(signal.aborted).toBe(false)
  } finally { api.dispose(); vi.useRealTimers() }
})
