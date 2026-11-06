import { it, expect, vi } from 'vitest'
import { createCanvasLayerCache } from './canvas_layer_cache.js'

it('reuses static pixels and invalidates for view, size and row changes', () => {
  const buffer = { setTransform: vi.fn() }, canvas = { getContext: () => buffer }
  const transform = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }
  const ctx = { canvas: { width: 800, height: 600 }, globalAlpha: 1, globalCompositeOperation: 'source-over',
    getTransform: () => transform, save: vi.fn(), restore: vi.fn(), setTransform: vi.fn(), drawImage: vi.fn() }
  const paint = vi.fn(), cache = createCanvasLayerCache(() => canvas), rows = []
  cache.draw(ctx, [rows, true], paint)
  cache.draw(ctx, [rows, true], paint)
  expect(paint).toHaveBeenCalledTimes(1)
  expect(ctx.drawImage).toHaveBeenCalledTimes(2)
  transform.e = 20
  cache.draw(ctx, [rows, true], paint)
  ctx.canvas.width = 900
  cache.draw(ctx, [rows, true], paint)
  cache.draw(ctx, [[], true], paint)
  cache.draw(ctx, [rows, false], paint)
  expect(paint).toHaveBeenCalledTimes(5)
  cache.clear()
  cache.draw(ctx, [rows, false], paint)
  expect(paint).toHaveBeenCalledTimes(6)
  expect(ctx.restore).toHaveBeenCalledTimes(7)
})

it('paints directly when per-stroke alpha or compositing must be preserved', () => {
  const paint = vi.fn(), create = vi.fn(), cache = createCanvasLayerCache(create)
  const ctx = { getTransform: () => ({}), globalAlpha: .5, globalCompositeOperation: 'source-over' }
  cache.draw(ctx, [], paint)
  ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'multiply'
  cache.draw(ctx, [], paint)
  expect(paint).toHaveBeenNthCalledWith(1, ctx)
  expect(paint).toHaveBeenNthCalledWith(2, ctx)
  expect(create).not.toHaveBeenCalled()
})
