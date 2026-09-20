/** Read the rendered canvas in the same frame, after normal rendering. No extra
 * render pass or preserveDrawingBuffer setting is added to measured rendering. */
export function snapshotViewer({ canvas, addFrameCallback, removeFrameCallback, inspect, timeoutMs = 5000 }) {
  return new Promise((resolve, reject) => {
    let settled = false
    const timer = setTimeout(() => finish(new Error('No rendered frame available for snapshot')), timeoutMs)
    function finish(error, value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      removeFrameCallback(frame)
      if (error) reject(error)
      else resolve(value)
    }
    function frame() {
      removeFrameCallback(frame)
      // The host renders synchronously after its frame callbacks; this microtask
      // reads those pixels before the browser presents/discards the drawing buffer.
      queueMicrotask(() => {
        if (settled) return
        try {
          const png = canvas.toDataURL('image/png')
          if (!png.startsWith('data:image/png;base64,')) throw new Error('Canvas snapshot unavailable')
          finish(null, { png, width: canvas.width, height: canvas.height, status: inspect(),
            scope: 'Viewer canvas only; captured outside timing; visual review required' })
        } catch (error) { finish(error) }
      })
    }
    addFrameCallback(frame)
  })
}
