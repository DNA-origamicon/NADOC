/** Cache a static canvas layer in screen pixels; the destination keeps its clip.
 * One image per destination context, replaced on size, transform or input changes.
 */
export function createCanvasLayerCache(createCanvas = () => document.createElement('canvas')) {
  let layers = new WeakMap()
  return {
    clear() { layers = new WeakMap() },
    draw(ctx, inputs, paint, background = null) {
      const transform = ctx.getTransform?.()
      // Nonstandard compositing cannot be moved from individual strokes to an image.
      if (!transform || ctx.globalAlpha !== 1 || ctx.globalCompositeOperation !== 'source-over') return paint(ctx)
      const { width, height } = ctx.canvas
      const strokeState = ['lineCap', 'lineJoin', 'miterLimit', 'lineDashOffset', 'shadowBlur', 'shadowColor', 'shadowOffsetX', 'shadowOffsetY']
      const dash = ctx.getLineDash?.() ?? []
      const key = [width, height, background, ...strokeState.map(k => ctx[k]), dash.join(','), ...['a', 'b', 'c', 'd', 'e', 'f'].map(k => transform[k]), ...inputs]
      let layer = layers.get(ctx)
      if (!layer || key.some((value, i) => value !== layer.key[i]) || key.length !== layer.key.length) {
        const canvas = layer?.canvas ?? createCanvas()
        canvas.width = width; canvas.height = height
        const buffer = canvas.getContext('2d')
        if (!buffer) return paint(ctx)
        if (background != null) {
          buffer.fillStyle = background
          buffer.fillRect(0, 0, width, height)
        }
        for (const key of strokeState) if (ctx[key] != null) buffer[key] = ctx[key]
        buffer.setLineDash?.(dash)
        buffer.setTransform(transform)
        paint(buffer)
        layer = { canvas, key, fillStyle: buffer.fillStyle, strokeStyle: buffer.strokeStyle, lineWidth: buffer.lineWidth }
        layers.set(ctx, layer)
      }
      ctx.save()
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.drawImage(layer.canvas, 0, 0)
      ctx.restore()
      // Match the state left by the direct painter for subsequent layers.
      ctx.fillStyle = layer.fillStyle; ctx.strokeStyle = layer.strokeStyle; ctx.lineWidth = layer.lineWidth
    },
  }
}
