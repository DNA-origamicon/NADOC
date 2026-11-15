/** Resize in viewport CSS pixels; keep the opposite edge fixed. */
export function resizeInsetRect(start, edge, dx, dy, bounds, minWidth = 160, minHeight = 120) {
  let { left, top, right, bottom } = start
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
  if (edge.includes('e')) right = clamp(start.right + dx, left + Math.min(minWidth, bounds.right - left), bounds.right)
  if (edge.includes('w')) left = clamp(start.left + dx, bounds.left, right - Math.min(minWidth, right - bounds.left))
  if (edge.includes('s')) bottom = clamp(start.bottom + dy, top + Math.min(minHeight, bounds.bottom - top), bounds.bottom)
  if (edge.includes('n')) top = clamp(start.top + dy, bounds.top, bottom - Math.min(minHeight, bottom - bounds.top))
  return { left, top, right, bottom, width: right - left, height: bottom - top }
}

/** Eight independent pointer handles; no native CSS resize observer/render loop. */
export function initZoomInsetResize({ host, getBounds, onResize, onCommit, minHeight = () => 146 }) {
  let drag = null
  const handles = ['n','s','e','w','ne','nw','se','sw'].map(edge => {
    const handle = host.ownerDocument.createElement('div')
    handle.className = `zoom-volume-resize zoom-volume-resize-${edge}`
    handle.dataset.resizeEdge = edge
    handle.setAttribute('aria-label', `Resize inset ${edge}`)
    handle.setAttribute('role', 'button'); handle.tabIndex = 0
    handle.onkeydown = event => {
      const step = event.shiftKey ? 25 : 10
      const delta = { ArrowLeft:[-step,0], ArrowRight:[step,0], ArrowUp:[0,-step], ArrowDown:[0,step] }[event.key]
      if (!delta) return
      onResize(resizeInsetRect(host.getBoundingClientRect(), edge, ...delta, getBounds(), 160, minHeight()))
      onCommit(); event.preventDefault(); event.stopPropagation()
    }
    handle.onpointerdown = event => {
      if (event.button !== 0) return
      drag = { pointer: event.pointerId, x: event.clientX, y: event.clientY, rect: host.getBoundingClientRect(), edge, handle }
      handle.setPointerCapture?.(event.pointerId)
      event.preventDefault(); event.stopPropagation()
    }
    handle.onpointermove = event => {
      if (!drag || drag.pointer !== event.pointerId) return
      onResize(resizeInsetRect(drag.rect, edge, event.clientX-drag.x, event.clientY-drag.y, getBounds(), 160, minHeight()))
      event.preventDefault(); event.stopPropagation()
    }
    const finish = (event, cancel) => {
      if (!drag || drag.pointer !== event.pointerId) return
      const current = drag; drag = null
      if (cancel) onResize(current.rect)
      if (handle.hasPointerCapture?.(event.pointerId)) handle.releasePointerCapture(event.pointerId)
      onCommit()
      event.stopPropagation()
    }
    handle.onpointerup = e => finish(e, false)
    handle.onpointercancel = e => finish(e, true)
    handle.onlostpointercapture = e => finish(e, false)
    host.append(handle)
    return handle
  })
  return { dispose() { drag = null; for (const h of handles) h.remove() } }
}
