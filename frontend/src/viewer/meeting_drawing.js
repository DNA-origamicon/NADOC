import { mountDrawingOverlay } from './meeting_drawing_overlay.js'

/** Touch Draw mode owns gestures; desktop drawing retains Shift + primary drag. */
export function mountMeetingDrawing({ parent, canvas, viewer, base, selfId, getRevision, ready, onActive = () => {}, document: doc = document, fetch: request = fetch }) {
  const mobile = !!viewer.mobile
  const button = doc.createElement('button'); button.type = 'button'; button.dataset.draw = ''; button.textContent = 'Draw'
  button.title = mobile ? 'Draw with one finger. Tap Draw again to rotate the view. Marks fade after two seconds.' : 'Hold Shift and drag with the left mouse button to point or circle. Marks fade after two seconds.'
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
    if (!enabled || !ready() || event.target !== canvas || (!mobile && !event.shiftKey)) return
    if (mobile) consume(event)
    if (event.button !== 0 || pointer !== null) return
    consume(event); pointer = event.pointerId; last = point(event)
    draft = make(last); overlay.local(draft); canvas.setPointerCapture?.(pointer)
  }
  function move(event) {
    if (mobile && enabled && event.target === canvas) consume(event)
    if (pointer === null || event.pointerId !== pointer) return
    consume(event)
    if ((!mobile && !event.shiftKey) || !(event.buttons & 1)) { end(event); return }
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
  function click(event) { if (enabled && (mobile || event.shiftKey) && event.button === 0 && event.target === canvas) consume(event) }
  const container = canvas.parentElement
  const listeners = [['pointerdown', down], ['pointermove', move], ['pointerup', end], ['pointercancel', end], ['click', click], ['dblclick', click]]
  for (const [type, handler] of listeners) container.addEventListener(type, handler, true)
  const timer = setInterval(flush, 80)
  function setEnabled(value) {
    if (enabled === value) return
    enabled = value; button.setAttribute('aria-pressed', String(enabled)); button.style.background = enabled ? '#238636' : ''
    status.textContent = enabled ? (mobile ? 'Drag to draw · Tap Draw again to rotate' : 'Shift + left drag to draw') : ''
    if (!enabled) {
      if (pointer !== null && canvas.hasPointerCapture?.(pointer)) canvas.releasePointerCapture(pointer)
      pointer = null; draft = null; last = null; overlay.clear(); pendingClear = true; void flush()
    }
    if (mobile) onActive(enabled)
  }
  button.onclick = () => setEnabled(!enabled)
  return { cancel() { setEnabled(false) }, update({ locked = false } = {}) {
    button.disabled = !ready() || (mobile && locked)
    if (mobile && button.disabled) setEnabled(false)
  }, receive(value) { color = value.participants?.find(p => p.id === selfId)?.color ?? color; overlay.receive(value) },
    dispose() { disposed = true; setEnabled(false); clearInterval(timer); abort.abort(); overlay.dispose(); button.remove(); status.remove(); for (const [type, handler] of listeners) container.removeEventListener(type, handler, true) },
  }
}
