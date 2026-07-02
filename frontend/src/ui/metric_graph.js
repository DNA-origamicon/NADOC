/**
 * metric_graph.js — vanilla-canvas line-chart renderer for the oxDNA "Graphs and
 * Metrics" card.  No external chart library (CSP/offline): the pure cores
 * (`niceTicks`, `dataToPixel`, `buildChartSpec`, `metricSeries`, `metricCSVs`)
 * compute a plain spec object that `drawChart` strokes onto a 2-D context and
 * `renderToDataURL` bakes to a PNG for export — so the exported image is exactly
 * what the popup shows.
 *
 * A "spec" is fully-computed pixel geometry (axes, ticks, per-series polylines,
 * legend) — separating it from the canvas keeps the layout math unit-testable.
 */

// Per-metric axis metadata (labels + units) for both domains.
export const METRIC_META = {
  twist: {
    label: 'Twist',
    spatial: { xLabel: 'axial position (nm)', yLabel: 'cum. twist, sim−analytic (deg)' },
    temporal: { xLabel: 'frame', yLabel: 'Δ twist (deg)' },
    zeroLine: true,
  },
  curvature: {
    label: 'Curvature',
    spatial: { xLabel: 'axial position (nm)', yLabel: 'cum. turning, sim−analytic (deg)' },
    temporal: { xLabel: 'frame', yLabel: 'Δ curvature (deg/nm)' },
    zeroLine: true,
  },
  base_pairing: {
    label: 'Base pairing',
    spatial: { xLabel: 'axial position (nm)', yLabel: 'fraction paired' },
    temporal: { xLabel: 'frame', yLabel: 'fraction paired' },
    zeroLine: false,
  },
}

// Overlay palette for per-job series (colour-blind-friendly-ish, distinct hues).
export const SERIES_COLORS = ['#58a6ff', '#f0883e', '#3fb950', '#bc8cff', '#f85149', '#e3b341']

// ── Pure cores ──────────────────────────────────────────────────────────────

function _niceNum(range, round) {
  if (range <= 0) return 1
  const exp = Math.floor(Math.log10(range))
  const f = range / Math.pow(10, exp)
  let nf
  if (round) nf = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10
  else nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10
  return nf * Math.pow(10, exp)
}

/** Nice, round tick values spanning [min, max] (~`count` of them). Degenerate
 *  ranges return a single tick. */
export function niceTicks(min, max, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
    return [Number.isFinite(min) ? min : 0]
  }
  const step = _niceNum((max - min) / Math.max(1, count - 1), true)
  const gMin = Math.floor(min / step) * step
  const gMax = Math.ceil(max / step) * step
  const ticks = []
  for (let v = gMin; v <= gMax + step * 0.5; v += step) ticks.push(Number(v.toFixed(6)))
  return ticks
}

/** Linear map of a data value onto a pixel coordinate (pMin↔dMin, pMax↔dMax). */
export function dataToPixel(v, dMin, dMax, pMin, pMax) {
  if (dMax === dMin) return (pMin + pMax) / 2
  return pMin + ((v - dMin) / (dMax - dMin)) * (pMax - pMin)
}

function _fmtTick(v) {
  if (v === 0) return '0'
  const a = Math.abs(v)
  if (a >= 1000 || a < 0.01) return v.toExponential(1)
  if (Number.isInteger(v)) return String(v)
  return v.toFixed(a < 1 ? 2 : 1)
}

/**
 * Build a fully-computed chart spec from `series` (each `{label, color,
 * points:[[x,y],…]}`).  Options: width/height, title, xLabel, yLabel, zeroLine,
 * and optional yMin/yMax overrides.  Empty input yields `{empty:true}`.
 */
export function buildChartSpec({
  series = [], width = 520, height = 300, title = '', xLabel = '', yLabel = '',
  zeroLine = false, yMin = null, yMax = null,
} = {}) {
  const pad = { l: 62, r: 16, t: title ? 30 : 14, b: 42 }
  const nonEmpty = series.filter(s => s.points && s.points.length)
  if (!nonEmpty.length) {
    return { empty: true, width, height, title, pad, series: [], xTicks: [], yTicks: [], legend: [] }
  }
  let xlo = Infinity, xhi = -Infinity, ylo = Infinity, yhi = -Infinity
  for (const s of nonEmpty) for (const [x, y] of s.points) {
    if (x < xlo) xlo = x; if (x > xhi) xhi = x
    if (y < ylo) ylo = y; if (y > yhi) yhi = y
  }
  if (yMin != null) ylo = Math.min(ylo, yMin)
  if (yMax != null) yhi = Math.max(yhi, yMax)
  if (zeroLine) { ylo = Math.min(ylo, 0); yhi = Math.max(yhi, 0) }
  if (ylo === yhi) { ylo -= 1; yhi += 1 }              // flat series → give it height
  const yTickVals = niceTicks(ylo, yhi, 5)
  ylo = Math.min(ylo, yTickVals[0]); yhi = Math.max(yhi, yTickVals[yTickVals.length - 1])
  const xTickVals = niceTicks(xlo, xhi, 6)

  const px0 = pad.l, px1 = width - pad.r, py0 = height - pad.b, py1 = pad.t
  const X = v => dataToPixel(v, xlo, xhi, px0, px1)
  const Y = v => dataToPixel(v, ylo, yhi, py0, py1)   // inverted (data up → pixel up)

  return {
    empty: false, width, height, pad, title, xLabel, yLabel,
    plot: { x0: px0, x1: px1, y0: py0, y1: py1 },
    xTicks: xTickVals.filter(v => v >= xlo - 1e-9 && v <= xhi + 1e-9)
      .map(v => ({ v, px: X(v), label: _fmtTick(v) })),
    yTicks: yTickVals.filter(v => v >= ylo - 1e-9 && v <= yhi + 1e-9)
      .map(v => ({ v, py: Y(v), label: _fmtTick(v) })),
    zeroY: zeroLine && ylo <= 0 && yhi >= 0 ? Y(0) : null,
    series: nonEmpty.map(s => ({
      label: s.label, color: s.color,
      pts: s.points.map(([x, y]) => [X(x), Y(y)]),
    })),
    legend: nonEmpty.length > 1 ? nonEmpty.map(s => ({ label: s.label, color: s.color })) : [],
  }
}

/** Extract renderable `{label,color,points}` series for a metric+domain from a
 *  metrics-run result.  Temporal → one series over the concatenated per-frame
 *  array (with faint job-boundary marks handled by the caller); spatial → one
 *  series per job (overlay). */
export function metricSeries(result, metric, domain) {
  if (!result || !result[metric]) return []
  const block = result[metric]
  if (domain === 'temporal') {
    const arr = block.temporal?.per_frame || []
    return arr.length ? [{ label: 'all frames', color: SERIES_COLORS[0],
                           points: arr.map((v, i) => [i, v]) }] : []
  }
  const jobs = block.spatial || []
  return jobs.map((jb, i) => ({
    label: _shortId(jb.job_id, i),
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    points: (jb.points || []).map(([t, v]) => [t, v]),
  }))
}

function _shortId(jobId, i) {
  return jobId ? `job ${String(jobId).slice(0, 6)}` : `job ${i + 1}`
}

/** CSV text for both domains of a metric → `{ temporal, spatial }`. */
export function metricCSVs(result, metric) {
  const block = result?.[metric] || {}
  const temporalRows = ['frame,value']
  const bounds = block.temporal?.boundaries || []
  const jobAt = i => {
    let jid = ''
    for (const b of bounds) if (i >= b.start_frame) jid = b.job_id
    return jid
  }
  const hasJobs = bounds.length > 1
  if (hasJobs) temporalRows[0] = 'frame,value,job_id'
  ;(block.temporal?.per_frame || []).forEach((v, i) => {
    temporalRows.push(hasJobs ? `${i},${v},${jobAt(i)}` : `${i},${v}`)
  })
  const spatialRows = ['job_id,axial_nm,value']
  ;(block.spatial || []).forEach(jb => {
    ;(jb.points || []).forEach(([t, v]) => spatialRows.push(`${jb.job_id},${t},${v}`))
  })
  return { temporal: temporalRows.join('\n') + '\n', spatial: spatialRows.join('\n') + '\n' }
}

// ── Canvas rendering (stateful shell over the pure spec) ─────────────────────

const _C = { grid: '#30363d', axis: '#8b949e', text: '#c9d1d9', bg: '#0d1117', zero: '#6e7681' }

/** Stroke a spec onto a 2-D canvas.  `canvas` is any element with getContext('2d'). */
export function drawChart(canvas, spec) {
  const ctx = canvas.getContext && canvas.getContext('2d')
  if (!ctx) return
  const { width, height } = spec
  canvas.width = width; canvas.height = height
  ctx.clearRect(0, 0, width, height)
  ctx.fillStyle = _C.bg; ctx.fillRect(0, 0, width, height)
  ctx.font = '11px var(--font-ui, sans-serif)'
  ctx.textBaseline = 'middle'

  if (spec.empty) {
    ctx.fillStyle = _C.axis; ctx.textAlign = 'center'
    ctx.fillText('No data', width / 2, height / 2)
    return
  }
  const { plot } = spec

  if (spec.title) {
    ctx.fillStyle = _C.text; ctx.textAlign = 'center'; ctx.font = '12px var(--font-ui, sans-serif)'
    ctx.fillText(spec.title, width / 2, spec.pad.t / 2)
    ctx.font = '11px var(--font-ui, sans-serif)'
  }
  // grid + y ticks
  ctx.textAlign = 'right'
  for (const t of spec.yTicks) {
    ctx.strokeStyle = _C.grid; ctx.beginPath(); ctx.moveTo(plot.x0, t.py); ctx.lineTo(plot.x1, t.py); ctx.stroke()
    ctx.fillStyle = _C.axis; ctx.fillText(t.label, plot.x0 - 6, t.py)
  }
  // x ticks
  ctx.textAlign = 'center'
  for (const t of spec.xTicks) {
    ctx.strokeStyle = _C.grid; ctx.beginPath(); ctx.moveTo(t.px, plot.y0); ctx.lineTo(t.px, plot.y0 + 4); ctx.stroke()
    ctx.fillStyle = _C.axis; ctx.fillText(t.label, t.px, plot.y0 + 15)
  }
  // zero reference line
  if (spec.zeroY != null) {
    ctx.strokeStyle = _C.zero; ctx.setLineDash([4, 3]); ctx.beginPath()
    ctx.moveTo(plot.x0, spec.zeroY); ctx.lineTo(plot.x1, spec.zeroY); ctx.stroke(); ctx.setLineDash([])
  }
  // axis frame
  ctx.strokeStyle = _C.axis; ctx.beginPath()
  ctx.moveTo(plot.x0, plot.y1); ctx.lineTo(plot.x0, plot.y0); ctx.lineTo(plot.x1, plot.y0); ctx.stroke()
  // series polylines
  for (const s of spec.series) {
    ctx.strokeStyle = s.color; ctx.lineWidth = 1.5; ctx.beginPath()
    s.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
    ctx.stroke(); ctx.lineWidth = 1
  }
  // axis labels
  ctx.fillStyle = _C.text; ctx.textAlign = 'center'
  if (spec.xLabel) ctx.fillText(spec.xLabel, (plot.x0 + plot.x1) / 2, height - 6)
  if (spec.yLabel) {
    ctx.save(); ctx.translate(12, (plot.y0 + plot.y1) / 2); ctx.rotate(-Math.PI / 2)
    ctx.fillText(spec.yLabel, 0, 0); ctx.restore()
  }
  // legend
  let lx = plot.x1 - 8
  ctx.textAlign = 'right'
  for (const item of spec.legend) {
    ctx.fillStyle = item.color
    const w = ctx.measureText(item.label).width
    ctx.fillRect(lx - w - 16, spec.pad.t + 2, 10, 8)
    ctx.fillStyle = _C.text; ctx.fillText(item.label, lx, spec.pad.t + 6)
    lx -= w + 26
  }
}

/** Render a spec to a PNG data URL via an offscreen canvas (for export). */
export function renderToDataURL(spec) {
  const c = document.createElement('canvas')
  drawChart(c, spec)
  return c.toDataURL('image/png')
}
