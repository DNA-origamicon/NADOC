import { it, expect, vi } from 'vitest'
import { PerspectiveCamera, Vector3 } from 'three'
import { cameraBetween, createSharedViewMotion } from './shared_view_motion.js'
const a = { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 2000, orbitMode: 'orbit' }
const b = { ...a, position: [0, 0, -20], up: [0, -1, 0] }
it('smoothly interpolates opposite orientations without passing through the target or losing up', () => {
  const middle = cameraBetween(a, b, .5)
  expect(new Vector3(...middle.position).length()).toBeCloseTo(20)
  expect(new Vector3(...middle.up).length()).toBeCloseTo(1)
  expect(middle.position).not.toEqual(a.position); expect(middle.position).not.toEqual(b.position)
  expect(cameraBetween(a, b, 1)).toBe(b)
})
it('animates over time, restores controls and cancels when the view changes', () => {
  const camera = new PerspectiveCamera(); camera.position.fromArray(a.position)
  const controls = { target: new Vector3(), enabled: true, enableDamping: true, update: vi.fn() }, canvas = document.createElement('canvas')
  let callback, context = 'one'
  const motion = createSharedViewMotion({ getView: () => ({ camera, controls, canvas, context }), now: () => 0, requestFrame: fn => { callback = fn; return 1 }, cancelFrame: vi.fn() })
  motion.move(b); expect(camera.position.toArray()).toEqual(a.position); expect(controls.enabled).toBe(false)
  callback(450); expect(camera.position.length()).toBeCloseTo(20)
  callback(900); expect(camera.position.toArray()).toEqual(b.position); expect(controls.enabled).toBe(true)
  motion.move(a); context = 'two'; callback(450); expect(controls.enabled).toBe(true); expect(camera.position.toArray()).toEqual(b.position)
  motion.move(a); canvas.dispatchEvent(new Event('pointerdown')); expect(controls.enabled).toBe(true); motion.dispose()
})
