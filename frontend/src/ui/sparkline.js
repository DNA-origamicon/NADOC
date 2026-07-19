/**
 * sparkline.js — a tiny no-axis line/area minigraph for the live "System monitor"
 * (CPU / GPU / RAM sparklines) in the simulation cards.  Deliberately separate from
 * the full charted `metric_graph.js` (which has axes, ticks, legends, 62px padding):
 * a sparkline is a bare trend line filling its whole box, redrawn a few times a
 * second, so it wants none of that machinery.  No external chart library (CSP/offline).
 *
 * The layout math is a pure function (`sparklinePath`) so it is unit-testable without
 * a canvas; `drawSparkline` is the thin stateful shell that strokes it.
 */

/**
 * Map a values array to polyline pixel points inside a `w`×`h` box (pure).
 *
 * The newest sample sits at the right edge; x is spread evenly left→right.  y scales
 * from [min,max] (defaults to the data's own range) with the data value UP mapping to
 * a smaller pixel y (screen up).  A flat series is centred.  Non-finite entries (e.g. a
 * `null` "n/a" GPU sample) become gaps: their point is omitted and the polyline is
 * split into separate segments so the line doesn't jump through missing data.
 *
 * @returns `{ segments: [[[x,y],…], …], empty: bool }` — one array of points per
 *          contiguous run of finite samples (usually a single segment).
 */
export function sparklinePath(values, w, h, { min = null, max = null, pad = 1 } = {}) {
  const arr = Array.isArray(values) ? values : []
  const finite = arr.filter(v => Number.isFinite(v))
  if (!finite.length) return { segments: [], empty: true }

  let lo = min == null ? Math.min(...finite) : min
  let hi = max == null ? Math.max(...finite) : max
  if (!(hi > lo)) hi = lo + 1                       // flat / degenerate → give it height

  const n = arr.length
  const x0 = pad, x1 = Math.max(pad, w - pad)
  const y0 = Math.max(pad, h - pad), y1 = pad       // y0 = bottom pixel, y1 = top
  const xAt = i => (n <= 1 ? x1 : x0 + (i / (n - 1)) * (x1 - x0))
  const yAt = v => y0 - ((v - lo) / (hi - lo)) * (y0 - y1)

  const segments = []
  let cur = null
  arr.forEach((v, i) => {
    if (Number.isFinite(v)) {
      if (!cur) { cur = []; segments.push(cur) }
      cur.push([xAt(i), yAt(v)])
    } else {
      cur = null                                    // gap → break the polyline
    }
  })
  return { segments, empty: false }
}

/**
 * Stroke a sparkline (optional soft area fill) onto a 2-D canvas.  Utilisation lines
 * pass `min:0, max:100` so the height reflects absolute % rather than autoscaling.
 */
export function drawSparkline(canvas, values, {
  color = '#58a6ff', min = null, max = null, fill = true, lineWidth = 1.25,
} = {}) {
  // getContext throws "Not implemented" under jsdom (no canvas pkg) — degrade to no-op.
  let ctx = null
  try { ctx = canvas && canvas.getContext && canvas.getContext('2d') } catch { ctx = null }
  if (!ctx) return
  const w = canvas.width, h = canvas.height
  ctx.clearRect(0, 0, w, h)
  const { segments, empty } = sparklinePath(values, w, h, { min, max })
  if (empty) return

  if (fill) {
    ctx.fillStyle = color + '22'                    // ~13% alpha wash under the line
    for (const pts of segments) {
      if (pts.length < 2) continue
      ctx.beginPath()
      pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
      ctx.lineTo(pts[pts.length - 1][0], h)
      ctx.lineTo(pts[0][0], h)
      ctx.closePath()
      ctx.fill()
    }
  }
  ctx.strokeStyle = color
  ctx.lineWidth = lineWidth
  ctx.lineJoin = 'round'
  for (const pts of segments) {
    ctx.beginPath()
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
    ctx.stroke()
  }
}
