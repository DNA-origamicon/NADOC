import { attachPoint, elbowPoints } from './annotation_layout.js'
/** Screen-space annotation geometry; never changes molecular coordinates. */
export const normalizeBoxAngle = value => Number.isFinite(value) ? ((value % 360 + 540) % 360) - 180 : 0
export function rotatedBoxSize(w, h, angle = 0) {
  const a = angle * Math.PI / 180, c = Math.abs(Math.cos(a)), s = Math.abs(Math.sin(a))
  return { w: w * c + h * s, h: w * s + h * c }
}
export function resizeAnnotationBox(start, handle, dx, dy, lockAspect = false) {
  const a = start.angle * Math.PI / 180, c = Math.cos(a), s = Math.sin(a)
  const x = dx * c + dy * s, y = -dx * s + dy * c
  const hx = handle.includes('e') ? 1 : handle.includes('w') ? -1 : 0
  const hy = handle.includes('s') ? 1 : handle.includes('n') ? -1 : 0
  let w = Math.max(32, Math.min(10000, start.w + hx * x))
  let h = Math.max(24, Math.min(10000, start.h + hy * y))
  if (lockAspect) {
    let scale = Math.abs(w / start.w - 1) > Math.abs(h / start.h - 1) ? w / start.w : h / start.h
    scale = Math.max(32 / start.w, 24 / start.h, Math.min(scale, 10000 / start.w, 10000 / start.h))
    w = start.w * scale; h = start.h * scale
  }
  const shiftX = hx * (w - start.w) / 2, shiftY = hy * (h - start.h) / 2
  return { w, h, cx: start.cx + shiftX * c - shiftY * s, cy: start.cy + shiftX * s + shiftY * c }
}

/** Attach leaders to the actual rotated edge, not its empty bounding-box corners. */
export function rotatedAnnotationLeader(type, rect, size, angle, anchor) {
  const a = angle * Math.PI / 180, c = Math.cos(a), s = Math.sin(a)
  const cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2
  const dx = anchor.x - cx, dy = anchor.y - cy
  const local = attachPoint({ x: -size.w / 2, y: -size.h / 2, ...size }, { x: dx * c + dy * s, y: -dx * s + dy * c }, type)
  const start = { x: cx + local.x * c - local.y * s, y: cy + local.x * s + local.y * c }
  return type === 'elbow' ? elbowPoints(start, anchor) : [start, anchor]
}
