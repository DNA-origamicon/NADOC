import { expect, it, vi } from 'vitest'
import { wireAnnotationBoxHandles } from './annotation_box_handles.js'
it('resizes without changing font size, cancels a gesture, and removes handlers on disposal', () => {
  const root = document.createElement('div'), box = document.createElement('div'), grip = document.createElement('div')
  root.append(box); box.append(grip)
  const update = vi.fn()
  const rec = { id: 'a', el: root, box, grip, entry: { manual: true, size: 2, rotationDeg: 0, boxSize: null, screenPos: { x: .2, y: .2 } },
    rect: { x: 100, y: 100, w: 200, h: 100 }, boxSize: { w: 200, h: 100 } }
  const dispose = wireAnnotationBoxHandles({ rec, root, controller: { update }, viewport: () => ({ width: 800, height: 600 }) })
  const handle = box.querySelector('[data-handle="e"]')
  const fire = (type, x) => handle.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX: x, clientY: 150, button: 0 }))
  fire('pointerdown', 300); fire('pointermove', 350)
  expect(update.mock.lastCall[1].boxSize).toEqual({ w: 250, h: 100 })
  expect(update.mock.lastCall[1]).not.toHaveProperty('size')
  fire('pointercancel', 350)
  expect(update.mock.lastCall[1].boxSize).toBeNull()
  rec.entry.manual = false; update.mockClear(); fire('pointerdown', 300); fire('pointermove', 350)
  expect(update).not.toHaveBeenCalled()
  dispose(); update.mockClear(); fire('pointerdown', 300); fire('pointermove', 350)
  expect(update).not.toHaveBeenCalled()
})
