import { expect, it, vi } from 'vitest'
import { drawAnnotationCallouts } from './annotation_canvas.js'
it('exports rotated box geometry and restores the DOM transform and canvas state', () => {
  const ctx = Object.fromEntries(['save', 'restore', 'scale', 'translate', 'rotate', 'beginPath', 'roundRect', 'fill', 'stroke'].map(key => [key, vi.fn()]))
  const box = document.createElement('div'); box.style.transform = 'rotate(90deg)'
  const text = document.createElement('span')
  drawAnnotationCallouts(ctx, [{ rect: { x: 40, y: 50, w: 80, h: 200 }, boxSize: { w: 200, h: 80 }, box, text,
    entry: { rotationDeg: 90, calloutType: 'elbow', transparency: 0, size: 1, color: '#ffffff' } }], 2)
  expect(ctx.translate).toHaveBeenCalledWith(80, 150)
  expect(ctx.rotate).toHaveBeenCalledWith(Math.PI / 2)
  expect(ctx.roundRect).toHaveBeenCalledWith(-99, -39, 198, 78, 0)
  expect(box.style.transform).toBe('rotate(90deg)')
  expect(ctx.save.mock.calls.length).toBe(ctx.restore.mock.calls.length)
})
