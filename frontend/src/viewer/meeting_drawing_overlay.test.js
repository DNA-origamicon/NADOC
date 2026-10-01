import { it, expect, vi } from 'vitest'
import { mountDrawingOverlay } from './meeting_drawing_overlay.js'
it('shows only matching views, fades on time, clears on motion and never replays a cleared mark', () => {
  document.body.innerHTML = '<main><canvas></canvas></main>'
  const canvas = document.querySelector('canvas'), camera = { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55 }
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 500 })
  let pose = camera, tick, now = 0
  const changed = vi.fn(), api = mountDrawingOverlay({ canvas, getView: () => ({ camera: pose, revision: 'r' }), onViewChange: changed, now: () => now, requestFrame: fn => { tick = fn; return 1 }, cancelFrame: vi.fn() })
  const mark = { id: 'a', author: 'guest', revision: 'r', camera, points: [[0, 0], [.2, .2]], expiresAt: 2500, color: '#abcdef' }
  api.receive({ drawings: [mark], serverTime: 0 }); tick()
  expect(document.querySelector('polyline').getAttribute('stroke')).toBe('#abcdef')
  expect(document.querySelector('svg').getAttribute('viewBox')).toBe('-1 -.5 2 1')
  now = 2250; tick(); expect(document.querySelector('polyline').getAttribute('opacity')).toBe('0.5')
  pose = { ...camera, position: [0, 0, 21] }; tick()
  expect(document.querySelector('polyline')).toBeNull(); expect(changed).toHaveBeenCalledOnce()
  pose = camera; tick(); api.receive({ drawings: [mark], serverTime: 2250 })
  expect(document.querySelector('polyline')).toBeNull()
  api.receive({ drawings: [{ ...mark, id: 'b', camera: { ...camera, fov: 60 } }], serverTime: 2250 })
  expect(document.querySelector('polyline')).toBeNull()
  api.dispose(); expect(document.querySelector('[data-meeting-drawing]')).toBeNull()
})
