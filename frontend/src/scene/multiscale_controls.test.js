import { it, expect } from 'vitest'
import { MOUSE, PerspectiveCamera, Vector3 } from 'three'
import { makeMultiscaleControls } from './multiscale_controls.js'
import { attachMouseBindings } from '../viewer/mouse_bindings.js'

function navigate(distance, remapped) {
  const canvas = document.createElement('canvas')
  canvas.setPointerCapture = () => {}; canvas.releasePointerCapture = () => {}
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 200 })
  Object.defineProperties(canvas, { clientWidth: { value: 200 }, clientHeight: { value: 200 } })
  const camera = new PerspectiveCamera(55, 1, .1, 2000)
  camera.position.set(distance, 0, 5); camera.lookAt(0, 0, 5); camera.updateMatrixWorld()
  const controls = makeMultiscaleControls(camera, canvas, new Vector3(0, 0, 5),
    () => new Float64Array([0, 0, 0, 0, 0, 10]))
  // Stock Trackball bindings used before the remap: right = PAN, middle = DOLLY.
  controls.mouseButtons.RIGHT = MOUSE.PAN
  const detach = remapped ? attachMouseBindings(canvas, () => controls) : () => {}
  const beforePan = camera.position.clone()
  for (const [type, x] of [['pointerdown', 50], ['pointermove', 90], ['pointerup', 90]]) {
    const e = new MouseEvent(type, { button: remapped ? 1 : 2, clientX: x, clientY: 50 })
    Object.defineProperties(e, { pointerId: { value: 1 }, pointerType: { value: 'mouse' } })
    canvas.dispatchEvent(e); controls.update(); camera.updateMatrixWorld()
  }
  const afterPan = camera.position.clone(), beforeWheel = camera.position.clone()
  canvas.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, clientX: 100, clientY: 100, cancelable: true }))
  controls.update()
  const afterWheel = camera.position.clone()
  detach(); controls.dispose()
  return { afterPan, afterWheel, panDistance: beforePan.distanceTo(afterPan), wheelDistance: beforeWheel.distanceTo(afterWheel) }
}

it.each([.5, 5, 50])('preserves old pan and wheel movement after remapping at distance %s', distance => {
  const old = navigate(distance, false), current = navigate(distance, true)
  expect(current.afterPan.distanceTo(old.afterPan)).toBeLessThan(1e-10)
  expect(current.afterWheel.distanceTo(old.afterWheel)).toBeLessThan(1e-10)
  expect(current.panDistance).toBeGreaterThan(0)
  expect(current.wheelDistance).toBeGreaterThan(0)
})

it('documents the existing local-scale slowdown near a helix independently of bindings', () => {
  const near = navigate(.5, true), far = navigate(50, true)
  expect(far.panDistance / near.panDistance).toBeGreaterThan(30)
  expect(far.wheelDistance / near.wheelDistance).toBeGreaterThan(30)
})
