import { mountDrawingOverlay } from './meeting_drawing_overlay.js'

/** Shift + primary pointer draws; all other gestures retain normal navigation. */
export function mountMeetingDrawing({ parent, canvas, viewer, base, selfId, getRevision, ready, document: doc = document, fetch: request = fetch }) {
  const button = doc.createElement('button'); button.type = 'button'; button.dataset.draw = ''; button.textContent = 'Draw'
  button.title = 'Hold Shift and drag with the left mouse button to point or circle. Marks fade after two seconds.'
  button.setAttribute('aria-pressed', 'false')
  const status = doc.createElement('span'); status.setAttribute('role', 'status'); status.dataset.drawingStatus = ''
  parent.append(button, status)
  let enabled = false, pointer = null, draft = null, last = null, flight = false, pendingClear = false, disposed = false, color = '#ffd166'
  const abort = new AbortController()
  const overlay = mountDrawingOverlay({ canvas, getView: () => ready() ? { camera: viewer.captureCamera(), revision: getRevision(), context: viewer.current } : null,
    onViewChange: () => { pointer = null; draft = null; last = null; pendingClear = true; void flush() } })
  function make(point) { return { id: crypto.randomUUID(), author: selfId, color, revision: getRevision(), camera: viewer.captureCamera(), points: [point] } }
  async function flush() {
    if (flight || disposed || (!draft && !pendingClear)) return
    const value = pendingClear ? { revision: getRevision(), clear: true } : draft
    if (pendingClear) pendingClear = false
    else draft = null
    flight = true
    try {
      const response = await request(`${base}/drawings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value), signal: abort.signal })
      if (!response.ok) throw new Error((await response.json()).error || 'Drawing could not be shared')
    } catch (error) { if (!disposed) status.textContent = error.message }
    finally { flight = false }
  }
  function point(event) { const r = canvas.getBoundingClientRect(); return [(event.clientX - r.left - r.width / 2) / r.height, (event.clientY - r.top - r.height / 2) / r.height] }
  function consume(event) { event.preventDefault(); event.stopImmediatePropagation() }
  function down(event) {
    if (!enabled || !ready() || !event.shiftKey || event.button !== 0 || event.target !== canvas) return
    consume(event); pointer = event.pointerId; last = point(event)
    draft = make(last); overlay.local(draft); canvas.setPointerCapture?.(pointer)
  }
  function move(event) {
    if (pointer === null || event.pointerId !== pointer) return
    consume(event)
    if (!event.shiftKey || !(event.buttons & 1)) { end(event); return }
    const next = point(event)
    draft ??= make(last)
    if (draft.points.length < 32) draft.points.push(next)
    else draft.points[draft.points.length - 1] = next
    last = next; overlay.local(draft)
  }
  function end(event) {
    if (pointer === null || event.pointerId !== pointer) return
    consume(event); canvas.releasePointerCapture?.(pointer); pointer = null; last = null; void flush()
  }
  function click(event) { if (enabled && event.shiftKey && event.button === 0 && event.target === canvas) consume(event) }
  const container = canvas.parentElement
  const listeners = [['pointerdown', down], ['pointermove', move], ['pointerup', end], ['pointercancel', end], ['click', click], ['dblclick', click]]
  for (const [type, handler] of listeners) container.addEventListener(type, handler, true)
  const timer = setInterval(flush, 80)
  button.onclick = () => { enabled = !enabled; button.setAttribute('aria-pressed', String(enabled)); button.style.background = enabled ? '#238636' : ''; status.textContent = enabled ? 'Shift + left drag to draw' : ''; if (!enabled) { pointer = null; draft = null; overlay.clear(); pendingClear = true; void flush() } }
  return { update() { button.disabled = !ready() }, receive(value) { color = value.participants?.find(p => p.id === selfId)?.color ?? color; overlay.receive(value) },
    dispose() { disposed = true; clearInterval(timer); abort.abort(); overlay.dispose(); button.remove(); status.remove(); for (const [type, handler] of listeners) container.removeEventListener(type, handler, true) },
  }
}
