import { it, expect } from 'vitest'
import { createSelectionDragGuard } from './selection_drag_guard.js'

const pointer = (canvas, type) => {
  const event = new MouseEvent(type, { button: 0, buttons: type === 'pointerup' ? 0 : 1, cancelable: true })
  canvas.dispatchEvent(event)
  return event
}

it('allows unclaimed gestures but rejects an already active tool', () => {
  const canvas = document.createElement('canvas'), controls = { enabled: true }
  const guard = createSelectionDragGuard(canvas, { controls })
  expect(guard.allows(pointer(canvas, 'pointerdown'))).toBe(true)
  controls.enabled = false
  expect(guard.allows(pointer(canvas, 'pointerdown'))).toBe(false)
  guard.dispose()
})

it('remembers a later gizmo claim even after pointerup re-enables navigation', async () => {
  const canvas = document.createElement('canvas'), controls = { enabled: true }
  const guard = createSelectionDragGuard(canvas, { controls })
  canvas.addEventListener('pointerdown', () => { controls.enabled = false })
  canvas.addEventListener('pointerup', () => { controls.enabled = true })
  pointer(canvas, 'pointerdown')
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(guard.allows()).toBe(false)
  pointer(canvas, 'pointerup')
  expect(controls.enabled).toBe(true)
  expect(guard.allows()).toBe(false)
  guard.dispose()
})

it('catches claims that begin on movement and resets only on a new press', () => {
  const canvas = document.createElement('canvas'), controls = { enabled: true }
  const guard = createSelectionDragGuard(canvas, { controls })
  pointer(canvas, 'pointerdown'); controls.enabled = false
  pointer(canvas, 'pointermove'); controls.enabled = true
  expect(guard.allows(pointer(canvas, 'pointerup'))).toBe(false)
  expect(guard.allows(pointer(canvas, 'pointerdown'))).toBe(true)
  guard.dispose()
})

it('respects consumed events and tools disabled through application state', async () => {
  const canvas = document.createElement('canvas')
  let disabled = false
  const guard = createSelectionDragGuard(canvas, { isDisabled: () => disabled })
  canvas.addEventListener('pointerdown', e => e.preventDefault(), { once: true })
  pointer(canvas, 'pointerdown'); await new Promise(resolve => setTimeout(resolve, 0))
  expect(guard.allows()).toBe(false)
  pointer(canvas, 'pointerdown'); disabled = true
  expect(guard.allows()).toBe(false)
  disabled = false
  expect(guard.allows()).toBe(false)
  guard.dispose()
})
