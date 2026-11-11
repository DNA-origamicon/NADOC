import { normalizeBoxAngle, resizeAnnotationBox, rotatedBoxSize } from './annotation_box_math.js'

/** Manual callout gestures. Pointer capture keeps resizing independent of orbit controls. */
export function wireAnnotationBoxHandles({ rec, root, controller, viewport }) {
  const doc = root.ownerDocument
  const controls = doc.createElement('div')
  controls.className = 'nadoc-anno__handles'
  for (const handle of ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w', 'rotate-nw', 'rotate-ne', 'rotate-se', 'rotate-sw']) {
    const button = doc.createElement('button')
    button.type = 'button'; button.dataset.handle = handle
    button.className = `nadoc-anno__handle nadoc-anno__handle--${handle}`
    button.setAttribute('aria-label', handle.startsWith('rotate') ? 'Rotate annotation' : `Resize annotation ${handle}`)
    button.title = handle.startsWith('rotate') ? 'Rotate; Shift snaps to 15°' : 'Resize; Shift preserves aspect ratio'
    if (handle.startsWith('rotate')) {
      button.classList.add('nadoc-anno__handle--rotate')
      button.innerHTML = '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M5 23 A18 18 0 0 1 23 5 V2 L30 7 L23 12 V9 A14 14 0 0 0 9 23 H12 L7 30 L2 23 Z" fill="currentColor" stroke="#0d3344" stroke-width="1.4" stroke-linejoin="miter"/></svg>'
    }
    controls.append(button)
  }
  rec.box.append(controls)
  let drag = null
  const point = event => {
    const bounds = root.getBoundingClientRect()
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top }
  }
  const down = event => {
    if ((event.button != null && event.button !== 0) || !rec.entry?.manual || controller.isPreviewing?.()) return
    const target = event.target.closest('[data-handle]') ?? rec.grip
    event.preventDefault(); event.stopPropagation()
    const p = point(event), rect = rec.rect
    if (!rect) return
    drag = { target, pointerId: event.pointerId, handle: target.dataset.handle ?? 'move',
      x: p.x, y: p.y, cx: rect.x + rect.w / 2, cy: rect.y + rect.h / 2,
      w: rec.boxSize?.w ?? rect.w, h: rec.boxSize?.h ?? rect.h,
      angle: rec.entry.rotationDeg ?? 0, rect, original: { manual: rec.entry.manual, boxSize: rec.entry.boxSize, rotationDeg: rec.entry.rotationDeg, screenPos: rec.entry.screenPos } }
    rec.drag = drag
    target.setPointerCapture?.(event.pointerId)
    rec.el.classList.add('nadoc-anno--dragging')
  }
  const move = event => {
    if (!drag || event.pointerId !== drag.pointerId) return
    event.preventDefault(); event.stopPropagation()
    const p = point(event), view = viewport()
    let { w, h, cx, cy, angle } = drag
    if (drag.handle === 'move') {
      cx += p.x - drag.x; cy += p.y - drag.y
    } else if (drag.handle.startsWith('rotate')) {
      const delta = Math.atan2(p.y - cy, p.x - cx) - Math.atan2(drag.y - cy, drag.x - cx)
      angle = normalizeBoxAngle(angle + delta * 180 / Math.PI)
      if (event.shiftKey) angle = Math.round(angle / 15) * 15
    } else ({ w, h, cx, cy } = resizeAnnotationBox(drag, drag.handle, p.x - drag.x, p.y - drag.y, event.shiftKey))
    const occupied = rotatedBoxSize(w, h, angle)
    controller.update(rec.id, { manual: true,
      ...(drag.handle !== 'move' ? { boxSize: { w, h }, rotationDeg: angle } : {}),
      screenPos: { x: (cx - occupied.w / 2) / view.width, y: (cy - occupied.h / 2) / view.height } })
  }
  const end = event => {
    if (!drag || (event.pointerId != null && event.pointerId !== drag.pointerId)) return
    const previous = drag; drag = null; rec.drag = null
    if (event.type === 'pointercancel' || event.key === 'Escape') controller.update(rec.id, previous.original)
    previous.target.releasePointerCapture?.(previous.pointerId)
    rec.el.classList.remove('nadoc-anno--dragging')
  }
  const key = event => { if (event.key === 'Escape' && drag) { event.preventDefault(); event.stopPropagation(); end(event) } }
  rec.box.addEventListener('pointerdown', down)
  rec.box.addEventListener('pointermove', move)
  rec.box.addEventListener('pointerup', end)
  rec.box.addEventListener('pointercancel', end)
  rec.box.addEventListener('lostpointercapture', end)
  doc.addEventListener('keydown', key, true)
  return () => {
    drag = null; rec.drag = null; controls.remove()
    rec.box.removeEventListener('pointerdown', down); rec.box.removeEventListener('pointermove', move)
    rec.box.removeEventListener('pointerup', end); rec.box.removeEventListener('pointercancel', end)
    rec.box.removeEventListener('lostpointercapture', end); doc.removeEventListener('keydown', key, true)
  }
}
