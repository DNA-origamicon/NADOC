import * as THREE from 'three'
import { createMeetingPing } from './meeting_ping.js'
import './selection_ping.css'

/** A local, finite visual pulse; only the event is transmitted, never animation frames. */
export function mountSelectionPing({ container, getCamera, getTarget, now = Date.now, sound = true }) {
  const doc = container.ownerDocument, ring = doc.createElement('div')
  ring.className = 'selection-ping'; ring.hidden = true; ring.setAttribute('aria-hidden', 'true'); container.append(ring)
  const dots = doc.createElement('canvas'); dots.className = 'selection-ping-points'; dots.hidden = true; dots.setAttribute('aria-hidden', 'true')
  let context = null, triedContext = false
  const chime = sound ? createMeetingPing({ document: doc }) : null
  const projected = new THREE.Vector3(), seen = new Set()
  let started = null, timer = null
  function clear() { started = null; ring.hidden = true; dots.hidden = true; dots.remove(); clearTimeout(timer); timer = null }
  function update() {
    if (started == null) return
    const elapsed = now() - started
    if (elapsed >= 2400) { clear(); return }
    const target = getTarget(), camera = getCamera(), attr = target?.geometry?.attributes.position
    if (!target || !camera || !attr?.count) { ring.hidden = true; dots.hidden = true; return }
    camera.updateMatrixWorld(); target.updateWorldMatrix(true, false)
    const w = container.clientWidth || 1, h = container.clientHeight || 1
    const pixels = []
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity
    for (let i = 0; i < attr.count; i++) {
      projected.fromBufferAttribute(attr, i).applyMatrix4(target.matrixWorld).project(camera)
      if (projected.z <= -1 || projected.z >= 1) continue
      const x = (projected.x + 1) * w / 2, y = (1 - projected.y) * h / 2
      if (i % Math.max(1, Math.ceil(attr.count / 5000)) === 0) pixels.push([x, y])
      left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y)
    }
    if (!Number.isFinite(left)) { ring.hidden = true; dots.hidden = true; return }
    const reduced = doc.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const phase = reduced ? 0 : (elapsed % 800) / 800, padding = 14 + phase * 22
    if (!triedContext) { triedContext = true; context = dots.getContext('2d') }
    if (context) {
      if (!dots.parentElement) container.append(dots)
      if (dots.width !== w || dots.height !== h) { dots.width = w; dots.height = h }
      context.clearRect(0, 0, w, h)
      dots.hidden = reduced || phase >= .3
      context.fillStyle = '#ffd166'; context.globalAlpha = .85
      for (const [x, y] of pixels) { context.beginPath(); context.arc(x, y, 6, 0, Math.PI * 2); context.fill() }
    }
    ring.hidden = false
    Object.assign(ring.style, { left: `${left - padding}px`, top: `${top - padding}px`, width: `${Math.max(12, right - left) + 2 * padding}px`, height: `${Math.max(12, bottom - top) + 2 * padding}px`, opacity: String(reduced ? 1 : 1 - phase * .85), backgroundColor: !reduced && phase < .22 ? 'rgba(255,209,102,.25)' : 'transparent' })
  }
  return { update, clear, play(event) {
    if (!event || seen.has(event.id) || now() - event.createdAt > 8000) return
    seen.add(event.id); if (seen.size > 64) seen.delete(seen.values().next().value)
    clear(); started = now(); chime?.play(); update(); timer = setTimeout(clear, 2400)
  }, dispose() { clear(); chime?.dispose(); ring.remove(); dots.remove() } }
}
