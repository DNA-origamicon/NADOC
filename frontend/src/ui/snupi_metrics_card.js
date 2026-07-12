/**
 * snupi_metrics_card.js — the "Graphs and Metrics" card in the SNUPI FEM Dynamics
 * section.  Sibling of cando_metrics_card.js: for the selected completed job it plots
 * the two per-base-pair FEM profiles — Flexibility (RMSF) and Deviation from design —
 * as spatial graphs and exports PNG / CSV.
 *
 * The FEM is a static solve so there is NO temporal domain and NO background compute —
 * the data is already cached on the completed job (rmsf.json + on-demand deviation).
 * The per-bp row builders / chart spec / CSV are engine-agnostic, so they're reused
 * from cando_metrics.js; only the endpoints (/snupi/*), DOM ids, and export filenames
 * differ.
 *
 * Factory: `initSnupiMetricsCard({ getSelectedJob })`.  A child module of the SNUPI
 * jobs panel.  Physical-layer / display-only readout; never mutates topology.
 */

import { getSnupiRmsf, getSnupiDeviation } from '../api/client.js'
import { drawChart, renderToDataURL } from './metric_graph.js'
import { CANDO_METRIC_META, rmsfRows, deviationRows, candoMetricCSV, buildCandoSpec } from './cando_metrics.js'
import {
  openMetricExportModal, exportChoiceFiles, downloadText, downloadHref,
} from './metric_export_modal.js'

const METRICS = [
  { key: 'rmsf', tok: 'rmsf' },
  { key: 'deviation', tok: 'dev' },
]

export function initSnupiMetricsCard({ getSelectedJob = null } = {}) {
  const card = document.getElementById('snupi-metrics-card')
  if (!card) return { refresh() {}, sync() {} }

  const toggle = document.getElementById('snupi-metrics-toggle')
  const arrow = document.getElementById('snupi-metrics-arrow')
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
      disp: document.getElementById(`snupi-metrics-${tok}-display`),
      exp: document.getElementById(`snupi-metrics-${tok}-export`),
      status: document.getElementById(`snupi-metrics-${tok}-status`),
    }
  }

  const _cache = new Map()

  function _job() {
    const j = getSelectedJob?.()
    return j && j.status === 'completed' ? j : null
  }

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

  function sync() {
    const job = _job()
    for (const { key } of METRICS) {
      const ok = _available(job, key)
      _style(rows[key].disp, !ok)
      _style(rows[key].exp, !ok)
      if (!job) _setStatus(rows[key], 'Select a completed SNUPI job.')
      else if (!ok) _setStatus(rows[key], 'Run a job with RMSF on for this map.', '#d29922')
      else if (!rows[key].status?.textContent) _setStatus(rows[key], 'Ready.')
    }
  }

  async function _fetchRows(job, metricKey) {
    const ck = `${job.job_id}:${metricKey}`
    if (_cache.has(ck)) return _cache.get(ck)
    let out
    if (metricKey === 'rmsf') out = rmsfRows(await getSnupiRmsf(job.job_id))
    else out = deviationRows(await getSnupiDeviation(job.job_id))
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
    const base = `snupi_${metricKey}_${job.job_id.slice(0, 8)}`
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
          <div id="snupi-metric-popup-title" style="font-size:15px;font-weight:600"></div>
          <button id="snupi-metric-popup-close"
            style="padding:5px 12px;background:#21262d;border:1px solid #30363d;
                   border-radius:6px;color:#c9d1d9;cursor:pointer">Close</button>
        </div>
        <canvas id="snupi-metric-popup-canvas" width="560" height="300"
                style="background:#0d1117;border:1px solid #21262d;border-radius:4px"></canvas>
      </div>`
    document.body.appendChild(overlay)
    _popup = overlay
    _popupTitle = overlay.querySelector('#snupi-metric-popup-title')
    _popupCanvas = overlay.querySelector('#snupi-metric-popup-canvas')
    const close = () => { _popup.style.display = 'none' }
    overlay.querySelector('#snupi-metric-popup-close').addEventListener('click', close)
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close() })
  }

  function _openPopup(metricKey, data) {
    _buildPopup()
    _popupTitle.textContent = CANDO_METRIC_META[metricKey]?.label || metricKey
    drawChart(_popupCanvas, buildCandoSpec(metricKey, data))
    _popup.style.display = 'flex'
  }

  for (const { key } of METRICS) {
    rows[key].disp?.addEventListener('click', () => _display(key))
    rows[key].exp?.addEventListener('click', () => _export(key))
  }
  sync()

  function refresh() {
    _cache.clear()
    for (const { key } of METRICS) _setStatus(rows[key], '')
    sync()
  }

  return { refresh, sync, _display, _export }
}
