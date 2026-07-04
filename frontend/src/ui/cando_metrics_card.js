/**
 * cando_metrics_card.js — the "Graphs and Metrics" card in the CanDo FEM Dynamics
 * section.  For the selected completed job it plots the two per-base-pair FEM
 * profiles — Flexibility (RMSF) and Deviation from design — as spatial graphs
 * (one overlaid polyline per helix) and exports PNG / CSV.
 *
 * Sibling of oxdna_metrics_card.js, simpler: the FEM is a static solve so there is
 * NO temporal domain and NO background compute — the data is already cached on the
 * completed job (rmsf.json + on-demand deviation), so a click just fetches + draws.
 * The RMSF row needs a job run with RMSF on; deviation is always available once solved.
 *
 * Factory: `initCandoMetricsCard({ getSelectedJob })`.  A child module of the CanDo
 * jobs panel (wired from initCandoJobsPanel) — owns its own DOM (by id), a per-job
 * results cache, and a lazily-built single-canvas Display popup.  Physical-layer /
 * display-only readout; never mutates topology.
 */

import { getCandoRmsf, getCandoDeviation } from '../api/client.js'
import { drawChart, renderToDataURL } from './metric_graph.js'
import { CANDO_METRIC_META, rmsfRows, deviationRows, candoMetricCSV, buildCandoSpec } from './cando_metrics.js'
import {
  openMetricExportModal, exportChoiceFiles, downloadText, downloadHref,
} from './metric_export_modal.js'

// Card metric key ↔ short DOM-id token.
const METRICS = [
  { key: 'rmsf', tok: 'rmsf' },
  { key: 'deviation', tok: 'dev' },
]

export function initCandoMetricsCard({ getSelectedJob = null } = {}) {
  const card = document.getElementById('cando-metrics-card')
  if (!card) return { refresh() {}, sync() {} }

  // Collapsible header (mirrors the panel's other .ox-card blocks) — starts collapsed.
  const toggle = document.getElementById('cando-metrics-toggle')
  const arrow = document.getElementById('cando-metrics-arrow')
  let _open = false
  toggle?.addEventListener('click', () => {
    _open = !_open
    card.style.display = _open ? '' : 'none'
    if (arrow) arrow.style.transform = _open ? 'rotate(90deg)' : ''
    if (_open) sync()
  })

  const rows = {}
  for (const { key, tok } of METRICS) {
    rows[key] = {
      disp: document.getElementById(`cando-metrics-${tok}-display`),
      exp: document.getElementById(`cando-metrics-${tok}-export`),
      status: document.getElementById(`cando-metrics-${tok}-status`),
    }
  }

  // Per-job cache of already-fetched rows, keyed "jobId:metric".
  const _cache = new Map()

  /** The selected job iff it is completed (only then are FEM profiles available). */
  function _job() {
    const j = getSelectedJob?.()
    return j && j.status === 'completed' ? j : null
  }

  /** Is a metric available for the current job? RMSF needs the job to have run NMA. */
  function _available(job, metricKey) {
    if (!job) return false
    if (metricKey === 'rmsf') return !!job.rmsf_max_nm
    return true
  }

  function _style(btn, disabled) {
    if (!btn) return
    btn.disabled = disabled
    btn.style.color = disabled ? '#484f58' : '#c9d1d9'
    btn.style.cursor = disabled ? 'not-allowed' : 'pointer'
  }

  function _setStatus(row, text, color = '#8b949e') {
    if (row?.status) { row.status.textContent = text; row.status.style.color = color }
  }

  /** Enable/disable the Display+Export buttons for the current selection. */
  function sync() {
    const job = _job()
    for (const { key } of METRICS) {
      const ok = _available(job, key)
      _style(rows[key].disp, !ok)
      _style(rows[key].exp, !ok)
      if (!job) _setStatus(rows[key], 'Select a completed CanDo job.')
      else if (!ok) _setStatus(rows[key], 'Run a job with RMSF on for this map.', '#d29922')
      else if (!rows[key].status?.textContent) _setStatus(rows[key], 'Ready.')
    }
  }

  /** Fetch (cached) the per-bp rows for a metric of the current job. */
  async function _fetchRows(job, metricKey) {
    const ck = `${job.job_id}:${metricKey}`
    if (_cache.has(ck)) return _cache.get(ck)
    let out
    if (metricKey === 'rmsf') out = rmsfRows(await getCandoRmsf(job.job_id))
    else out = deviationRows(await getCandoDeviation(job.job_id))
    _cache.set(ck, out)
    return out
  }

  async function _display(metricKey) {
    const job = _job()
    if (!_available(job, metricKey)) return
    const row = rows[metricKey]
    _setStatus(row, 'Loading…')
    let data
    try { data = await _fetchRows(job, metricKey) } catch (e) {
      _setStatus(row, 'Load failed: ' + (e?.message || 'error'), '#f85149'); return
    }
    if (!data.length) { _setStatus(row, 'No data for this metric.', '#d29922'); return }
    _openPopup(metricKey, data)
    _setStatus(row, `${data.length} base pairs.`, '#3fb950')
  }

  async function _export(metricKey) {
    const job = _job()
    if (!_available(job, metricKey)) return
    const row = rows[metricKey]
    let data
    try { data = await _fetchRows(job, metricKey) } catch (e) {
      _setStatus(row, 'Load failed: ' + (e?.message || 'error'), '#f85149'); return
    }
    if (!data.length) { _setStatus(row, 'No data for this metric.', '#d29922'); return }
    const choice = await openMetricExportModal()
    if (!choice) return
    const kinds = exportChoiceFiles(choice)
    const base = `cando_${metricKey}_${job.job_id.slice(0, 8)}`
    if (kinds.includes('png')) {
      downloadHref(`${base}.png`, renderToDataURL(buildCandoSpec(metricKey, data)))
    }
    if (kinds.includes('data')) {
      downloadText(`${base}.csv`, candoMetricCSV(data, CANDO_METRIC_META[metricKey]?.valueHeader))
    }
  }

  // ── Display popup (single spatial canvas; lazily built, reused) ──────────────
  let _popup = null, _popupTitle = null, _popupCanvas = null
  function _buildPopup() {
    if (_popup) return
    const overlay = document.createElement('div')
    overlay.style.cssText = [
      'position:fixed;inset:0;z-index:10000',
      'background:rgba(0,0,0,0.55);display:none',
      'align-items:center;justify-content:center',
      'font-family:var(--font-ui, sans-serif)',
    ].join(';')
    overlay.innerHTML = `
      <div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;
                  padding:16px;max-width:95vw;max-height:92vh;overflow:auto;color:#c9d1d9">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:16px">
          <div id="cando-metric-popup-title" style="font-size:15px;font-weight:600"></div>
          <button id="cando-metric-popup-close"
            style="padding:5px 12px;background:#21262d;border:1px solid #30363d;
                   border-radius:6px;color:#c9d1d9;cursor:pointer">Close</button>
        </div>
        <canvas id="cando-metric-popup-canvas" width="560" height="300"
                style="background:#0d1117;border:1px solid #21262d;border-radius:4px"></canvas>
      </div>`
    document.body.appendChild(overlay)
    _popup = overlay
    _popupTitle = overlay.querySelector('#cando-metric-popup-title')
    _popupCanvas = overlay.querySelector('#cando-metric-popup-canvas')
    const close = () => { _popup.style.display = 'none' }
    overlay.querySelector('#cando-metric-popup-close').addEventListener('click', close)
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close() })
  }

  function _openPopup(metricKey, data) {
    _buildPopup()
    _popupTitle.textContent = CANDO_METRIC_META[metricKey]?.label || metricKey
    drawChart(_popupCanvas, buildCandoSpec(metricKey, data))
    _popup.style.display = 'flex'
  }

  // Wire.
  for (const { key } of METRICS) {
    rows[key].disp?.addEventListener('click', () => _display(key))
    rows[key].exp?.addEventListener('click', () => _export(key))
  }
  sync()

  /** Called by the panel when the design/selection changes → cached rows are stale. */
  function refresh() {
    _cache.clear()
    for (const { key } of METRICS) _setStatus(rows[key], '')
    sync()
  }

  return { refresh, sync, _display, _export }   // last two exposed for tests
}
