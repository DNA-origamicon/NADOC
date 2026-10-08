import { it, expect } from 'vitest'
import { PerspectiveCamera } from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { TrackballControls } from 'three/addons/controls/TrackballControls.js'
import { configureMouseBindings, attachMouseBindings } from './mouse_bindings.js'

for (const Controller of [OrbitControls, TrackballControls]) {
  it(`${Controller.name}: only right-drag orbits, middle pans, left and Ctrl-drags do not navigate`, () => {
    const canvas = document.createElement('canvas')
    canvas.setPointerCapture = () => {}; canvas.releasePointerCapture = () => {}
    canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 200 })
    Object.defineProperties(canvas, { clientWidth: { value: 200 }, clientHeight: { value: 200 } })
    const camera = new PerspectiveCamera(50, 1, .1, 100)
    camera.position.z = 10
    const controls = new Controller(camera, canvas)
    controls.staticMoving = true
    configureMouseBindings(controls)
    const detach = attachMouseBindings(canvas, () => controls)
    function drag(button, ctrlKey = false) {
      for (const [type, x] of [['pointerdown', 50], ['pointermove', 90], ['pointerup', 90]]) {
        const e = new MouseEvent(type, { button, ctrlKey, clientX: x, clientY: 50 })
        Object.defineProperties(e, { pointerId: { value: 1 }, pointerType: { value: 'mouse' } })
        canvas.dispatchEvent(e)
        controls.update()
      }
    }
    const position = camera.position.clone(), target = controls.target.clone()
    drag(0); drag(0, true); drag(2, true)
    expect(camera.position.distanceTo(position)).toBeLessThan(1e-8)
    expect(controls.target.distanceTo(target)).toBeLessThan(1e-8)
    drag(2)
    expect(camera.position.distanceTo(position)).toBeGreaterThan(.1)
    expect(controls.target.distanceTo(target)).toBeLessThan(1e-8)
    drag(1)
    expect(controls.target.distanceTo(target)).toBeGreaterThan(.1)
    detach(); controls.dispose()
  })
}
