/**
 * shape_compare_card.js — the cross-engine "Shape comparison" card (S5).
 *
 * Closes the shared-metric track: the S1–S4 math put every structure-prediction engine
 * (oxDNA · CanDo · mrDNA · NAMD) on one comparable footing; this card GENERATES that
 * comparison for the current design, VIEWS it (a scalar table with signed %-deltas vs the
 * per-observable reference, a per-engine RMSF overlay, an agreement table, and an E-field
 * deflection panel), and EXPORTS it (PNG of the overlay + CSV of the tables).
 *
 * Factory `initShapeCompareCard({ api, getSources })`:
 *   - `api`        — `{ start(body) → {metrics_id}, poll(runId) → {state, progress,
 *                    result?} }` (the `/shape/compare` REST surface).
 *   - `getSources` — `() → [source bundle]` (may be async): the per-engine
 *                    `{engine, descriptors?, rmsf?, shape_frame?, field?}` bundles for the
 *                    current design.  Until the per-engine emission tasks land (O1/C5/M5/N4)
 *                    this returns `[]` and the card reports that no predictions are ready.
 *
 * The graph/export machinery (metric_graph, metric_export_modal) is reused verbatim — the
 * card owns only its own DOM (by id), the poll loop, and the last report.  It renders
 * Physical-layer numbers only (Three-Layer Law).  `main.js` LOC-Δ = 0 (wired from a panel).
 */

import {
  SERIES_COLORS, buildChartSpec, drawChart, renderToDataURL,
} from './metric_graph.js'
import {
  openMetricExportModal, exportChoiceFiles, downloadText, downloadHref,
} from './metric_export_modal.js'

const POLL_MS = 300

// Human labels + units for the comparable scalar descriptors (report row order).
export const SCALAR_LABELS = {
  twist_total_deg: 'Twist total (°)',
  twist_per_turn_deg: 'Twist / turn (°)',
  bend_angle_deg: 'Bend angle (°)',
  bend_radius_nm: 'Bend radius (nm)',
  radius_of_gyration_nm: 'Radius of gyration (nm)',
  end_to_end_nm: 'End-to-end (nm)',
  axial_span_nm: 'Axial span (nm)',
}

// ── Pure formatting + view-model helpers (unit-tested) ───────────────────────

/** Format a number to `digits` sig-figs; `null`/`undefined`/non-finite → an em dash. */
export function fmtNum(v, digits = 2) {
  if (v == null || !Number.isFinite(v)) return '—'
  return Number(v).toFixed(digits)
}

/** Format a signed percent delta with an explicit sign (`+3.1%`), `null` → em dash. */
export function fmtDelta(pct) {
  if (pct == null || !Number.isFinite(pct)) return '—'
  return `${pct >= 0 ? '+' : ''}${Number(pct).toFixed(1)}%`
}

/**
 * View-model for the scalar table: `{ engines, reference, rows }` where each row is
 * `{ name, label, cells:[{engine, value, deltaPct, isReference}] }` in the report's engine
 * column order.  Pure derivation from a `build_comparison_report` payload.
 */
export function scalarTableModel(report) {
  const engines = report?.engines || []
  const reference = report?.references?.shape ?? null
  const rows = (report?.scalars || []).map(r => ({
    name: r.name,
    label: SCALAR_LABELS[r.name] || r.name,
    cells: engines.map(e => ({
      engine: e,
      value: r.cells?.[e]?.value ?? null,
      deltaPct: r.cells?.[e]?.signed_pct_delta ?? null,
      isReference: e === reference,
    })),
  }))
  return { engines, reference, rows }
}

/**
 * A `buildChartSpec` spec overlaying each engine's RMSF profile (one series per engine,
 * reference engine drawn first).  Empty (no profiles) → an `{empty:true}` spec.
 */
export function rmsfOverlaySpec(report, { width = 520, height = 260 } = {}) {
  const profiles = (report?.rmsf_profiles || []).slice()
  // Reference engine first so its colour is stable across regenerations.
  profiles.sort((a, b) => (b.is_reference ? 1 : 0) - (a.is_reference ? 1 : 0))
  const series = profiles.map((p, i) => ({
    label: p.is_reference ? `${p.engine} (ref)` : p.engine,
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    points: (p.points || []).map(([x, y]) => [x, y]),
  }))
  return buildChartSpec({
    series, width, height, title: 'Per-bp RMSF (flexibility)',
    xLabel: 'base-pair ordinal', yLabel: 'RMSF (nm)',
  })
}

/** CSV text for the comparison → `{ scalars, agreement, field }` (field '' when absent). */
export function comparisonCSVs(report) {
  const engines = report?.engines || []
  const ref = report?.references?.shape ?? ''
  // Scalars: one row per descriptor, a value + delta column per engine.
  const sHead = ['descriptor', ...engines.flatMap(e => [`${e}`, `${e}_pct_vs_ref`])]
  const sRows = [sHead.join(',')]
  for (const r of (report?.scalars || [])) {
    const cells = engines.flatMap(e => {
      const c = r.cells?.[e] || {}
      const pct = c.signed_pct_delta
      return [c.value ?? '', pct == null ? '' : pct]
    })
    sRows.push([r.name, ...cells].join(','))
  }
  const scalarsCSV = `# shape reference: ${ref}\n${sRows.join('\n')}\n`

  // Agreement: one row per candidate engine.
  const aRows = ['engine,shape_rmsd_nm,rmsf_pearson,rmsf_spearman,rmsf_n,field_cosine,field_magnitude_ratio']
  for (const a of (report?.agreement || [])) {
    aRows.push([
      a.engine, a.shape_rmsd_nm ?? '',
      a.rmsf?.pearson ?? '', a.rmsf?.spearman ?? '', a.rmsf?.n ?? '',
      a.field?.cosine_similarity ?? '', a.field?.magnitude_ratio ?? '',
    ].join(','))
  }
  const agreementCSV = `${aRows.join('\n')}\n`

  let fieldCSV = ''
  if (report?.field?.rows?.length) {
    const fRows = ['engine,is_reference,anchored_max_drift_nm,free_proj_along_field_nm,passed,cosine_vs_ref,magnitude_ratio']
    for (const f of report.field.rows) {
      fRows.push([
        f.engine, f.is_reference ? 1 : 0, f.anchored_max_drift_nm ?? '',
        f.free_proj_along_field_nm ?? '', f.passed == null ? '' : (f.passed ? 1 : 0),
        f.cosine_vs_ref ?? '', f.magnitude_ratio ?? '',
      ].join(','))
    }
    fieldCSV = `# field reference: ${report.field.reference ?? ''}\n${fRows.join('\n')}\n`
  }
  return { scalars: scalarsCSV, agreement: agreementCSV, field: fieldCSV }
}

// ── HTML builders (pure string → innerHTML; engine names are controlled tokens) ──

function _scalarTableHTML(report) {
  const m = scalarTableModel(report)
  if (!m.engines.length) return '<div style="color:#8b949e">No descriptors.</div>'
  const head = `<tr><th style="text-align:left">descriptor</th>${
    m.engines.map(e => `<th>${e === m.reference ? `${e} · ref` : e}</th>`).join('')}</tr>`
  const body = m.rows.map(r => `<tr><td style="text-align:left;color:#c9d1d9">${r.label}</td>${
    r.cells.map(c => {
      const d = c.isReference || c.deltaPct == null ? ''
        : ` <span style="color:${c.deltaPct >= 0 ? '#3fb950' : '#f0883e'}">(${fmtDelta(c.deltaPct)})</span>`
      return `<td>${fmtNum(c.value)}${d}</td>`
    }).join('')}</tr>`).join('')
  return `<table style="width:100%;border-collapse:collapse;font-size:var(--text-xs);color:#8b949e">${head}${body}</table>`
}

function _agreementTableHTML(report) {
  const rows = report?.agreement || []
  if (!rows.length) return '<div style="color:#8b949e">Need ≥2 engines with a shared observable to score agreement.</div>'
  const head = '<tr><th style="text-align:left">engine</th><th>shape RMSD (nm)</th><th>RMSF r</th><th>RMSF ρ</th><th>field cos</th><th>field ratio</th></tr>'
  const body = rows.map(a => `<tr><td style="text-align:left;color:#c9d1d9">${a.engine}</td>` +
    `<td>${fmtNum(a.shape_rmsd_nm, 3)}</td><td>${fmtNum(a.rmsf?.pearson, 3)}</td>` +
    `<td>${fmtNum(a.rmsf?.spearman, 3)}</td><td>${fmtNum(a.field?.cosine_similarity, 3)}</td>` +
    `<td>${fmtNum(a.field?.magnitude_ratio, 2)}</td></tr>`).join('')
  return `<table style="width:100%;border-collapse:collapse;font-size:var(--text-xs);color:#8b949e">${head}${body}</table>`
}

function _fieldTableHTML(report) {
  const field = report?.field
  if (!field?.rows?.length) return ''
  const head = `<div style="font-size:var(--text-xs);color:#c9d1d9;margin:8px 0 4px">E-field deflection (ref: ${field.reference ?? '—'})</div>` +
    '<table style="width:100%;border-collapse:collapse;font-size:var(--text-xs);color:#8b949e">' +
    '<tr><th style="text-align:left">engine</th><th>anchor drift (nm)</th><th>free ∥ field (nm)</th><th>held+deflected</th><th>cos vs ref</th></tr>'
  const body = field.rows.map(f => `<tr><td style="text-align:left;color:#c9d1d9">${f.engine}${f.is_reference ? ' · ref' : ''}</td>` +
    `<td>${fmtNum(f.anchored_max_drift_nm)}</td><td>${fmtNum(f.free_proj_along_field_nm)}</td>` +
    `<td>${f.passed == null ? '—' : (f.passed ? '✓' : '✗')}</td><td>${fmtNum(f.cosine_vs_ref, 3)}</td></tr>`).join('')
  return `${head}${body}</table>`
}

// ── Factory ──────────────────────────────────────────────────────────────────

export function initShapeCompareCard({ api, getSources = () => [] } = {}) {
  const card = document.getElementById('shape-compare-card')
  if (!card) return { refresh() {} }

  const toggle = document.getElementById('shape-compare-toggle')
  const arrow = document.getElementById('shape-compare-arrow')
  let _open = false
  toggle?.addEventListener('click', () => {
    _open = !_open
    card.style.display = _open ? '' : 'none'
    if (arrow) arrow.style.transform = _open ? 'rotate(90deg)' : ''
  })

  const genBtn = document.getElementById('shape-compare-gen')
  const expBtn = document.getElementById('shape-compare-export')
  const status = document.getElementById('shape-compare-status')
  const bar = document.getElementById('shape-compare-bar')
  const fill = document.getElementById('shape-compare-fill')
  const scalarsEl = document.getElementById('shape-compare-scalars')
  const agreementEl = document.getElementById('shape-compare-agreement')
  const fieldEl = document.getElementById('shape-compare-field')
  const canvas = document.getElementById('shape-compare-rmsf')

  let _report = null
  let _busy = false
  let _pollTimer = null

  function _setStatus(text, color = '#8b949e') {
    if (status) { status.textContent = text; status.style.color = color }
  }
  function _setBar(frac) {
    if (!fill || !bar) return
    if (frac == null) { bar.style.display = 'none'; return }
    bar.style.display = 'block'
    fill.style.width = `${Math.round(Math.max(0, Math.min(1, frac)) * 100)}%`
  }
  function _styleBtns() {
    const ready = !!_report?.ready
    if (genBtn) { genBtn.disabled = _busy; genBtn.style.cursor = _busy ? 'not-allowed' : 'pointer' }
    if (expBtn) {
      expBtn.disabled = _busy || !ready
      expBtn.style.color = (_busy || !ready) ? '#484f58' : '#c9d1d9'
      expBtn.style.cursor = (_busy || !ready) ? 'not-allowed' : 'pointer'
    }
  }

  /** Render a completed report into the card's tables + overlay. */
  function render(report) {
    _report = report
    if (scalarsEl) scalarsEl.innerHTML = _scalarTableHTML(report)
    if (agreementEl) agreementEl.innerHTML = _agreementTableHTML(report)
    if (fieldEl) fieldEl.innerHTML = _fieldTableHTML(report)
    if (canvas) drawChart(canvas, rmsfOverlaySpec(report, { width: canvas.width || 520 }))
    _styleBtns()
  }

  async function _generate() {
    if (_busy) return
    _busy = true; _styleBtns(); _setBar(0)
    _setStatus('Gathering engine predictions…')
    let sources
    try { sources = await getSources() } catch (e) {
      _fail('Could not gather sources: ' + (e?.message || 'error')); return
    }
    if (!sources || !sources.length) {
      _busy = false; _setBar(null); _styleBtns()
      _setStatus('No engine predictions available yet — run oxDNA / CanDo and emit ' +
        'descriptors for this design (O1/C5/M5/N4).', '#d29922')
      return
    }
    let start
    try { start = await api.start({ sources }) } catch (e) {
      _fail('Could not start: ' + (e?.message || 'error')); return
    }
    _poll(start.metrics_id, sources.length)
  }

  function _poll(runId, nSources) {
    const tick = async () => {
      let st
      try { st = await api.poll(runId) } catch (e) {
        _fail('Poll failed: ' + (e?.message || 'error')); return
      }
      _setBar(st.progress ?? 0)
      if (st.state === 'running') {
        _setStatus('Comparing…'); _pollTimer = setTimeout(tick, POLL_MS); return
      }
      _busy = false
      if (st.state === 'error') { _fail('Error: ' + (st.error || 'unknown')); return }
      const report = st.result
      if (!report?.ready) {
        _setBar(null); _setStatus(report?.reason || 'No comparison produced.', '#d29922')
        _styleBtns(); return
      }
      _setBar(1)
      render(report)
      const nCmp = report.agreement?.length || 0
      _setStatus(`Ready — ${report.engines.length} engine(s), ${nCmp} scored. ` +
        `Reference: shape=${report.references.shape ?? '—'}, rmsf=${report.references.rmsf ?? '—'}.`,
        '#3fb950')
    }
    tick()
  }

  function _fail(msg) {
    _busy = false; _setBar(null); _setStatus(msg, '#f85149'); _styleBtns()
  }

  async function _export() {
    if (!_report?.ready) return
    const choice = await openMetricExportModal()
    if (!choice) return
    const kinds = exportChoiceFiles(choice)
    if (kinds.includes('png')) {
      downloadHref('shape_compare_rmsf.png', renderToDataURL(rmsfOverlaySpec(_report)))
    }
    if (kinds.includes('data')) {
      const csv = comparisonCSVs(_report)
      downloadText('shape_compare_scalars.csv', csv.scalars)
      downloadText('shape_compare_agreement.csv', csv.agreement)
      if (csv.field) downloadText('shape_compare_field.csv', csv.field)
    }
  }

  genBtn?.addEventListener('click', _generate)
  expBtn?.addEventListener('click', _export)
  _styleBtns()

  /** Panel calls this when the design changes → the cached comparison is stale. */
  function refresh() {
    _report = null
    if (scalarsEl) scalarsEl.innerHTML = ''
    if (agreementEl) agreementEl.innerHTML = ''
    if (fieldEl) fieldEl.innerHTML = ''
    _setBar(null); _setStatus(''); _styleBtns()
  }

  return { refresh, render, _generate, _export }   // render + actions exposed for tests
}
