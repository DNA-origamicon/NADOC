import { cameraBetween } from './shared_view_motion.js'

/** Same 0.9-second orbit transition as a saved view, then smooth live tracking. */
export function createPresenterFollow({ viewer, now = () => performance.now() }) {
  let start = null, began = 0, previous = 0
  return {
    start() { start = viewer.captureCamera(); began = previous = now() },
    stop() { start = null },
    frame(camera) {
      const time = now(), elapsed = Math.max(0, time - began)
      if (start && elapsed < 900) {
        const t = elapsed / 900
        viewer.applyCamera(cameraBetween(start, camera, t * t * (3 - 2 * t)), 1, { resetControls: false })
      } else {
        start = null
        viewer.applyCamera(camera, 1 - Math.exp(-Math.min(100, Math.max(0, time - previous)) / 70))
      }
      previous = time
    },
  }
}
