import { mountDrawingOverlay } from './meeting_drawing_overlay.js'

/** Read-only host channel; guest marks appear only at the matching camera pose. */
export function initEditorDrawings({ prepared, getRoom, document: doc = document, fetch: request = fetch }) {
  let overlay = null, canvas = null, revision = null, context = null, flight = false, disposed = false
  let abort = new AbortController()
  function clear() {
    abort.abort(); abort = new AbortController()
    overlay?.dispose(); overlay = null; canvas = null
  }
  const source = () => prepared.captureView(true)
  const timer = setInterval(async () => {
    if (flight || disposed || doc.hidden) return
    const room = getRoom()
    if (!room) { overlay?.dispose(); overlay = null; canvas = null; return }
    flight = true
    const signal = abort.signal
    try {
      const response = await request(`/__nadoc_share/shares/${room.id}/drawings`, { headers: { 'X-NADOC-Share': '1' }, signal })
      if (!response.ok) return
      const value = await response.json()
      if (disposed || signal.aborted || getRoom()?.id !== room.id) return
      const view = source()
      if (view.canvas !== canvas) { overlay?.dispose(); overlay = null; canvas = view.canvas }
      revision = value.revision; context = room.id
      if (!canvas) return
      overlay ??= mountDrawingOverlay({ canvas,
        getBounds: () => { const pane = source().pane; return (pane ? doc.querySelector(`.mv-viewport-panel[data-panel="${pane}"]`) : null)?.getBoundingClientRect() ?? canvas.getBoundingClientRect() },
        getView: () => { const current = source(); return getRoom()?.id === context ? { camera: current.pose, context: current.scene, revision } : null } })
      overlay.receive(value)
    } catch { overlay?.clear() }
    finally { flight = false }
  }, 200)
  return { clear, dispose() { disposed = true; clearInterval(timer); clear() } }
}
