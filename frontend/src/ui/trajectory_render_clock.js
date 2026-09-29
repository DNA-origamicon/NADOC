// Follow the renderer in desktop and WebXR; fall back to RAF without a renderer.
const pending = new Map()
let serial = 0, drivers = 0
export function requestTrajectoryFrame(callback) {
  const id = ++serial, item = { callback, fallback: null }
  pending.set(id, item)
  if (!drivers) item.fallback = requestAnimationFrame(time => {
    if (!pending.delete(id)) return
    callback(time)
  })
  return id
}
export function cancelTrajectoryFrame(id) {
  const item = pending.get(id)
  if (item?.fallback != null) cancelAnimationFrame(item.fallback)
  pending.delete(id)
}
export function attachTrajectoryRenderClock() {
  drivers++
  for (const item of pending.values()) {
    if (item.fallback != null) cancelAnimationFrame(item.fallback)
    item.fallback = null
  }
  let attached = true
  return {
    tick(time = performance.now()) {
      if (!attached) return
      for (const [id, item] of [...pending]) {
        if (!pending.delete(id)) continue
        item.callback(time)
      }
    },
    dispose() {
      if (!attached) return
      attached = false
      if (--drivers) return
      for (const [id, item] of pending) item.fallback = requestAnimationFrame(time => {
        if (!pending.delete(id)) return
        item.callback(time)
      })
    },
  }
}
