import { MOUSE } from 'three'

export function configureMouseBindings(controls) {
  controls.mouseButtons.LEFT = null
  controls.mouseButtons.MIDDLE = MOUSE.PAN
  controls.mouseButtons.RIGHT = MOUSE.ROTATE
}

// Capture phase runs before either camera controller starts a gesture.
export function attachMouseBindings(canvas, getControls) {
  const down = event => {
    const controls = getControls()
    configureMouseBindings(controls)
    if (event.ctrlKey || event.metaKey) controls.mouseButtons.RIGHT = null
  }
  canvas.addEventListener('pointerdown', down, true)
  return () => canvas.removeEventListener('pointerdown', down, true)
}
