/**
 * cando_metrics.js — pure cores for the CanDo FEM "Graphs and Metrics" card.
 *
 * The FEM is a STATIC solve (no trajectory), so — unlike the oxDNA metrics card —
 * both CanDo metrics are purely SPATIAL, per base pair, with no temporal domain:
 *
 *   • Flexibility (RMSF)  — per-bp RMSF (nm) from the free-free normal-mode analysis.
 *   • Deviation           — per-bp distance of the FEM-predicted shape from the
 *                            design's intended (displayed) geometry (nm).
 *
 * These helpers turn a /cando/jobs/{id}/rmsf or /deviation response into per-helix
 * chart series (x = bp index, one polyline per helix, overlaid) + CSV text, and reuse
 * metric_graph.js's `buildChartSpec` for the pixel geometry so the popup + PNG export
 * share exactly one layout path.  All pure / unit-tested; the DOM shell lives in
 * cando_metrics_card.js.
 */

import { buildChartSpec, SERIES_COLORS } from './metric_graph.js'

// Helix ids are strings (e.g. "h_XY_0_1"); numeric-aware compare keeps h_..._2 < h_..._10.
const _cmpHelix = (a, b) => String(a).localeCompare(String(b), undefined, { numeric: true })

// Per-metric axis metadata (labels + units + CSV value column).
export const CANDO_METRIC_META = {
  rmsf: {
    label: 'Flexibility (RMSF)',
    xLabel: 'base-pair index',
    yLabel: 'RMSF (nm)',
    valueHeader: 'rmsf_nm',
  },
  deviation: {
    label: 'Deviation from design',
    xLabel: 'base-pair index',
    yLabel: 'deviation from intended (nm)',
    valueHeader: 'deviation_nm',
  },
}

// ── Response → per-bp rows [{helix, bp, val}] ────────────────────────────────

/** RMSF response → per-bp rows.  One entry per FEM (duplex-core) node. */
export function rmsfRows(rmsfResp) {
  if (!rmsfResp?.rmsf?.length) return []
  const out = []
  for (const r of rmsfResp.rmsf) {
    if (!Number.isFinite(r.rmsf_nm)) continue
    out.push({ helix: r.helix_id, bp: r.bp_index, val: r.rmsf_nm })
  }
  return out
}

/** Deviation response → per-bp rows.  Multiple nucleotides (both strands + loop
 *  copies) map to one (helix, bp) axis station, so their deviation is averaged into
 *  a single per-bp value for the profile. */
export function deviationRows(devResp) {
  if (!devResp?.positions?.length) return []
  const acc = new Map()   // "helix:bp" → {helix, bp, sum, n}
  for (const p of devResp.positions) {
    if (!Number.isFinite(p.deviation)) continue
    const key = `${p.helix_id}:${p.bp_index}`
    const cur = acc.get(key) || { helix: p.helix_id, bp: p.bp_index, sum: 0, n: 0 }
    cur.sum += p.deviation
    cur.n += 1
    acc.set(key, cur)
  }
  return [...acc.values()].map((a) => ({ helix: a.helix, bp: a.bp, val: a.sum / a.n }))
}

// ── Rows → chart series / CSV (pure) ─────────────────────────────────────────

/** Group per-bp rows into one `{label, color, points:[[bp,val],…]}` series per
 *  helix (sorted by helix id, points sorted by bp) for an overlaid spatial chart. */
export function helixSeries(rows) {
  if (!rows?.length) return []
  const byHelix = new Map()
  for (const r of rows) {
    if (!byHelix.has(r.helix)) byHelix.set(r.helix, [])
    byHelix.get(r.helix).push([r.bp, r.val])
  }
  const helices = [...byHelix.keys()].sort(_cmpHelix)
  return helices.map((h, i) => ({
    label: `helix ${h}`,
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    points: byHelix.get(h).sort((a, b) => a[0] - b[0]),
  }))
}

/** CSV text for a metric's rows: `helix_id,bp_index,<valueHeader>` (sorted). */
export function candoMetricCSV(rows, valueHeader) {
  const header = `helix_id,bp_index,${valueHeader || 'value'}`
  const sorted = [...(rows || [])].sort((a, b) => _cmpHelix(a.helix, b.helix) || a.bp - b.bp)
  return [header, ...sorted.map((r) => `${r.helix},${r.bp},${r.val}`)].join('\n') + '\n'
}

/** Build the (single, spatial) chart spec for a CanDo metric from its per-bp rows.
 *  Reused by both the Display popup and the PNG export so they render identically. */
export function buildCandoSpec(metric, rows, { width = 560, height = 300 } = {}) {
  const meta = CANDO_METRIC_META[metric] || {}
  return buildChartSpec({
    series: helixSeries(rows),
    width, height,
    title: `${meta.label || metric} — per base pair along each helix`,
    xLabel: meta.xLabel || 'base-pair index',
    yLabel: meta.yLabel || '',
    yMin: 0,
  })
}
