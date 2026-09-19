import { clearanceAt, coverage, emptyCentres } from './annotation_occupancy.js'

/**
 * Pure screen-space layout for annotation callouts. Rectangles are
 * `{x, y, w, h}` in CSS px relative to the overlay's top-left.
 */

export const MARGIN = 8
const AUTO_OFFSET = { x: 36, y: 48 }
const STACK_GAP = 6

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi))

export function clampRect(rect, viewport) {
  return {
    ...rect,
    x: clamp(rect.x, MARGIN, viewport.width - rect.w - MARGIN),
    y: clamp(rect.y, MARGIN, viewport.height - rect.h - MARGIN),
  }
}

/** Default box for a callout: up-and-right of its anchor, flipped away from edges. */
export function preferredRect(anchor, size, viewport) {
  let x = anchor.x + AUTO_OFFSET.x
  let y = anchor.y - AUTO_OFFSET.y - size.h
  if (x + size.w > viewport.width - MARGIN) x = anchor.x - AUTO_OFFSET.x - size.w
  if (y < MARGIN) y = anchor.y + AUTO_OFFSET.y * 0.6
  return clampRect({ x, y, w: size.w, h: size.h }, viewport)
}

const overlaps = (a, b) =>
  a.x < b.x + b.w + STACK_GAP && b.x < a.x + a.w + STACK_GAP &&
  a.y < b.y + b.h + STACK_GAP && b.y < a.y + a.h + STACK_GAP

/** Nudge `rect` down (then wrapping) until it clears every obstacle. */
export function clearOverlaps(rect, obstacles, viewport) {
  let r = clampRect(rect, viewport)
  for (let i = 0; i < 24; i++) {
    const hit = obstacles.find(o => overlaps(r, o))
    if (!hit) return r
    r = clampRect({ ...r, y: hit.y + hit.h + STACK_GAP }, viewport)
    if (r.y + r.h > viewport.height - MARGIN) r = { ...r, y: MARGIN, x: r.x + 24 }
  }
  return r
}

const RING_DISTANCES = [46, 90, 150, 230]
const RING_ANGLES = 16
const COVERAGE_WEIGHT = 1200
const OVERLAP_PENALTY = 6000
const LEADER_WEIGHT = 0.35
const CLEARANCE_WEIGHT = 0.6
const CLEARANCE_CAP = 70
/** A previous auto position is kept unless something is this much better (stops orbit jitter). */
const STICKY_MARGIN = 60

const boxOverlapsAny = (rect, obstacles) => obstacles.some(o => overlaps(rect, o))

/** Lower is better. Coverage of the design dominates; then leader length and roominess. */
export function scoreRect(rect, anchor, occupancy, obstacles) {
  let score = COVERAGE_WEIGHT * coverage(occupancy, rect)
  if (boxOverlapsAny(rect, obstacles)) score += OVERLAP_PENALTY
  const cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2
  score -= CLEARANCE_WEIGHT * Math.min(clearanceAt(occupancy, cx, cy), CLEARANCE_CAP)
  if (anchor) {
    // Distance from the anchor to the nearest point of the box ≈ leader length.
    const nx = Math.min(Math.max(anchor.x, rect.x), rect.x + rect.w)
    const ny = Math.min(Math.max(anchor.y, rect.y), rect.y + rect.h)
    score += LEADER_WEIGHT * Math.hypot(anchor.x - nx, anchor.y - ny)
  }
  return score
}

/**
 * Pick the auto position that covers least of the visible design: ring candidates
 * around the anchor plus the centres of the roomiest empty pockets. With no
 * anchor the box simply goes to the middle of the emptiest space.
 */
export function placeAuto({ anchor, size, viewport, occupancy, obstacles, previous }) {
  const candidates = []
  const push = (cx, cy) => candidates.push(clampRect({ x: cx - size.w / 2, y: cy - size.h / 2, w: size.w, h: size.h }, viewport))
  if (anchor) {
    for (const d of RING_DISTANCES) {
      for (let i = 0; i < RING_ANGLES; i++) {
        const a = (i / RING_ANGLES) * Math.PI * 2
        // Box centre sits so its NEAR edge is ~d from the anchor, not its centre.
        const reach = d + Math.abs(Math.cos(a)) * size.w / 2 + Math.abs(Math.sin(a)) * size.h / 2
        push(anchor.x + Math.cos(a) * reach, anchor.y + Math.sin(a) * reach)
      }
    }
    candidates.push(preferredRect(anchor, size, viewport))
  }
  for (const c of emptyCentres(occupancy, anchor ? 3 : 6)) push(c.x, c.y)
  if (!candidates.length) push(viewport.width / 2, viewport.height / 2)

  let best = null, bestScore = Infinity
  for (const rect of candidates) {
    const s = scoreRect(rect, anchor, occupancy, obstacles)
    if (s < bestScore) { bestScore = s; best = rect }
  }
  if (previous) {
    const kept = clampRect({ ...previous, w: size.w, h: size.h }, viewport)
    if (scoreRect(kept, anchor, occupancy, obstacles) <= bestScore + STICKY_MARGIN) return kept
  }
  return best
}

/**
 * Lay out every callout. Manual boxes are fixed obstacles placed first; auto
 * boxes are placed by `placeAuto` when an occupancy grid is supplied (else the
 * simple up-and-right default). Returns Map id → rect.
 * @param items [{ id, size:{w,h}, anchor:{x,y}|null, manualRect:{x,y}|null }]
 * @param options { occupancy, previous: Map id → rect }
 */
export function layoutCallouts(items, viewport, { occupancy = null, previous = null } = {}) {
  const placed = new Map()
  const obstacles = []
  for (const item of items) {
    if (!item.manualRect) continue
    const rect = clampRect({ x: item.manualRect.x, y: item.manualRect.y, w: item.size.w, h: item.size.h }, viewport)
    placed.set(item.id, rect)
    obstacles.push(rect)
  }
  for (const item of items) {
    if (item.manualRect) continue
    let rect
    if (occupancy) {
      rect = placeAuto({ anchor: item.anchor, size: item.size, viewport, occupancy, obstacles, previous: previous?.get(item.id) })
    } else {
      const start = item.anchor
        ? preferredRect(item.anchor, item.size, viewport)
        : { x: MARGIN * 2, y: MARGIN * 2, w: item.size.w, h: item.size.h }
      rect = clearOverlaps(start, obstacles, viewport)
    }
    placed.set(item.id, rect)
    obstacles.push(rect)
  }
  return placed
}

/**
 * Attachment point on a box edge for a leader heading to `anchor`. The side is
 * re-chosen every frame, so it flips as the box lands left/right/above/below.
 */
export function attachPoint(rect, anchor, type) {
  const cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2
  if (type === 'shelf') {
    return { x: anchor.x >= cx ? rect.x + rect.w : rect.x, y: rect.y + rect.h }
  }
  if (type === 'elbow') {
    // Anchor directly above/below the box: leave from the top/bottom centre.
    if (anchor.x >= rect.x && anchor.x <= rect.x + rect.w) return { x: cx, y: anchor.y < cy ? rect.y : rect.y + rect.h }
    return { x: anchor.x >= cx ? rect.x + rect.w : rect.x, y: cy }
  }
  const candidates = [
    { x: cx, y: rect.y }, { x: cx, y: rect.y + rect.h },
    { x: rect.x, y: cy }, { x: rect.x + rect.w, y: cy },
  ]
  let best = candidates[0], bestD = Infinity
  for (const c of candidates) {
    const d = (c.x - anchor.x) ** 2 + (c.y - anchor.y) ** 2
    if (d < bestD) { bestD = d; best = c }
  }
  return best
}

/** Horizontal run then a 45° diagonal into the anchor (the NAMD callout style). */
export function elbowPoints(start, end) {
  const dx = end.x - start.x, dy = end.y - start.y
  const sx = Math.sign(dx) || 1, sy = Math.sign(dy) || 1
  if (Math.abs(dx) >= Math.abs(dy)) {
    return [start, { x: end.x - sx * Math.abs(dy), y: start.y }, end]
  }
  return [start, { x: end.x, y: start.y + sy * Math.abs(dx) }, end]
}

/** Polyline for a callout's leader. */
export function leaderPoints(type, rect, anchor) {
  const start = attachPoint(rect, anchor, type)
  if (type === 'elbow') return elbowPoints(start, anchor)
  return [start, anchor]
}
