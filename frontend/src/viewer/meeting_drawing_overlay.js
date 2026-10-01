import { drawingOpacity, sameDrawingView, DRAW_LIFETIME_MS } from './meeting_drawing_protocol.js'

/** Camera-bound screen overlay, shared by guest viewers and the editor. */
export function mountDrawingOverlay({ canvas, getView, getBounds = () => canvas.getBoundingClientRect(), onViewChange = () => {},
  now = () => performance.now(), requestFrame = requestAnimationFrame, cancelFrame = cancelAnimationFrame }) {
  const doc = canvas.ownerDocument, ns = 'http://www.w3.org/2000/svg'
  const svg = doc.createElementNS(ns, 'svg'); svg.dataset.meetingDrawing = ''
  svg.setAttribute('aria-hidden', 'true')
  svg.style.cssText = 'position:absolute;pointer-events:none;overflow:hidden;z-index:15;'
  canvas.parentElement.append(svg)
  const records = new Map(), blocked = new Map()
  let previous = null, frameId, disposed = false
  const key = mark => `${mark.author ?? 'local'}:${mark.id}`
  function clear() {
    for (const [id, record] of records) { blocked.set(id, record.expires); record.node.remove() }
    records.clear()
  }
  function view() { try { return getView() } catch { return null } }
  function add(mark, expires, remote) {
    const id = key(mark), current = view()
    if (blocked.has(id) || !current || mark.revision !== current.revision || !sameDrawingView(mark.camera, current.camera) || expires <= now()) return
    let record = records.get(id)
    if (!record) {
      const node = doc.createElementNS(ns, 'polyline')
      node.setAttribute('fill', 'none'); node.setAttribute('stroke-width', '3'); node.setAttribute('vector-effect', 'non-scaling-stroke')
      node.setAttribute('stroke-linecap', 'round'); node.setAttribute('stroke-linejoin', 'round')
      node.style.filter = 'drop-shadow(0 0 1px #000)'
      svg.append(node); record = { node, expires, remote }; records.set(id, record)
    }
    record.remote ||= remote; record.expires = Math.min(record.expires, expires)
    const points = mark.points.length === 1 ? [mark.points[0], [mark.points[0][0] + .00001, mark.points[0][1]]] : mark.points
    record.node.setAttribute('points', points.map(p => p.join(',')).join(' '))
    record.node.setAttribute('stroke', /^#[a-f0-9]{6}$/i.test(mark.color) ? mark.color : '#ffd166')
  }
  function frame() {
    if (disposed) return
    const current = view()
    if (previous && (!current || current.context !== previous.context || current.revision !== previous.revision || !sameDrawingView(previous.camera, current.camera))) { const hadMarks = records.size > 0; clear(); if (hadMarks) onViewChange() }
    previous = current
    let rect
    try { rect = getBounds() } catch { rect = canvas.getBoundingClientRect() }
    const parent = canvas.parentElement.getBoundingClientRect()
    if (rect.height > 0) {
      Object.assign(svg.style, { left: `${rect.left - parent.left}px`, top: `${rect.top - parent.top}px`, width: `${rect.width}px`, height: `${rect.height}px` })
      svg.setAttribute('viewBox', `${-rect.width / rect.height / 2} -.5 ${rect.width / rect.height} 1`)
    }
    for (const [id, record] of records) {
      const opacity = drawingOpacity(DRAW_LIFETIME_MS - (record.expires - now()))
      if (!opacity) { record.node.remove(); records.delete(id); blocked.set(id, now() + DRAW_LIFETIME_MS) }
      else record.node.setAttribute('opacity', String(opacity))
    }
    for (const [id, expiry] of blocked) if (expiry <= now()) blocked.delete(id)
    frameId = requestFrame(frame)
  }
  frameId = requestFrame(frame)
  return { clear, local(mark) { add(mark, now() + DRAW_LIFETIME_MS, false) },
    receive(value) {
      const ids = new Set((value.drawings ?? []).map(key))
      for (const [id, record] of records) if (record.remote && !ids.has(id)) { record.node.remove(); records.delete(id) }
      for (const mark of value.drawings ?? []) add(mark, now() + Math.max(0, Math.min(DRAW_LIFETIME_MS, mark.expiresAt - value.serverTime)), true)
    },
    dispose() { disposed = true; cancelFrame(frameId); records.clear(); blocked.clear(); svg.remove() },
  }
}
