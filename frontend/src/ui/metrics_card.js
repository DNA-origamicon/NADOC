/**
 * metrics_card.js — the engine-agnostic "Graphs and Metrics" card factory shared by
 * the oxDNA Dynamics panel and the MD (NAMD) panel.  For a job (or its whole
 * parent/child lineage) it computes twist, curvature and base-pairing over the
 * production trajectory and lets the user view them as annotated spatial + temporal
 * graphs, watch an ETA loading bar while they compute, and export PNG / CSV.
 *
 * Factory: `initMetricsCard({ idPrefix, api, getSelectedJob, getJobs })`.
 *   - `idPrefix`   — DOM id namespace: `${idPrefix}-card`, `${idPrefix}-${tok}-gen`, …
 *                    (`oxdna-metrics` or `md-metrics`).
 *   - `api`        — `{ start(jobId, body) → {metrics_id}, poll(runId) → {state,…} }`,
 *                    the only engine-specific dependency (oxDNA vs MD REST surface).
 *   - `getSelectedJob` / `getJobs` — the panel's current selection + list.
 *
 * A child module of a jobs panel — it owns its own DOM (by id), the poll loop, and a
 * per-scope results cache.  One background compute yields all three metrics (single
 * trajectory pass), so any metric's Generate populates the whole card; each metric
 * keeps its own buttons + progress bar.  The graph popup / export modules
 * (metric_graph*, metric_export_modal) are fully engine-agnostic and reused verbatim.
 */

import { METRIC_META, metricCSVs, renderToDataURL } from './metric_graph.js'
import { metricSpecs, openMetricGraphPopup } from './metric_graph_popup.js'
import {
  openMetricExportModal, exportChoiceFiles, downloadText, downloadHref,
} from './metric_export_modal.js'

// Card metric key ↔ short DOM-id token.
const METRICS = [
  { key: 'twist', tok: 'twist' },
  { key: 'curvature', tok: 'curve' },
  { key: 'base_pairing', tok: 'bp' },
]

const POLL_MS = 400

export function initMetricsCard({ idPrefix, api, getSelectedJob = null, getJobs = null } = {}) {
  const card = document.getElementById(`${idPrefix}-card`)
  if (!card) return { refresh() {} }

  // Collapsible header (mirrors the panel's Advanced .ox-card) — starts collapsed.
  const toggle = document.getElementById(`${idPrefix}-toggle`)
  const arrow = document.getElementById(`${idPrefix}-arrow`)
  let _open = false
  toggle?.addEventListener('click', () => {
    _open = !_open
    card.style.display = _open ? '' : 'none'
    if (arrow) arrow.style.transform = _open ? 'rotate(90deg)' : ''
  })

  const scopeLatest = document.getElementById(`${idPrefix}-scope-latest`)
  const scopeChain = document.getElementById(`${idPrefix}-scope-chain`)
  const rows = {}
  for (const { key, tok } of METRICS) {
    rows[key] = {
      gen: document.getElementById(`${idPrefix}-${tok}-gen`),
      disp: document.getElementById(`${idPrefix}-${tok}-display`),
      exp: document.getElementById(`${idPrefix}-${tok}-export`),
      bar: document.getElementById(`${idPrefix}-${tok}-bar`),
      fill: document.getElementById(`${idPrefix}-${tok}-fill`),
      status: document.getElementById(`${idPrefix}-${tok}-status`),
    }
  }

  // Per-scope cache of the last completed run result ({twist, curvature, base_pairing}).
  const _cache = { latest: null, chain: null }
  let _runningMetric = null            // the metric key whose Generate is in flight
  let _pollTimer = null

  const _scope = () => (scopeChain?.checked ? 'chain' : 'latest')

  function _activeJobId() {
    const sel = getSelectedJob?.()
    if (sel?.job_id) return sel.job_id
    const jobs = (getJobs?.() || []).slice()
    if (!jobs.length) return null
    jobs.sort((a, b) => (b.created_at || 0) - (a.created_at || 0))   // newest first
    return jobs[0].job_id
  }

  function _setBar(row, frac) {
    if (!row.fill) return
    if (frac == null) { row.bar.style.display = 'none'; return }
    row.bar.style.display = 'block'
    row.fill.style.width = `${Math.round(Math.max(0, Math.min(1, frac)) * 100)}%`
  }

  function _setStatus(row, text, color = '#8b949e') {
    if (row.status) { row.status.textContent = text; row.status.style.color = color }
  }

  function _style(btn, disabled) {
    if (!btn) return
    btn.disabled = disabled
    btn.style.color = disabled ? '#484f58' : '#c9d1d9'
    btn.style.cursor = disabled ? 'not-allowed' : 'pointer'
  }

  function _updateButtons() {
    const busy = _runningMetric != null
    const result = _cache[_scope()]
    for (const { key } of METRICS) {
      const row = rows[key]
      const ready = !!(result?.ready && result[key])
      _style(row.gen, busy)
      _style(row.disp, busy || !ready)
      _style(row.exp, busy || !ready)
    }
    if (scopeLatest) scopeLatest.disabled = busy
    if (scopeChain) scopeChain.disabled = busy
  }

  async function _generate(metricKey) {
    if (_runningMetric) return
    const jobId = _activeJobId()
    const row = rows[metricKey]
    if (!jobId) { _setStatus(row, 'Select or run a job first.', '#d29922'); return }
    _runningMetric = metricKey
    _updateButtons()
    _setBar(row, 0)
    _setStatus(row, 'Starting…')
    let start
    try {
      start = await api.start(jobId, { scope: _scope() })
    } catch (e) {
      _fail(row, 'Could not start: ' + (e?.message || 'error')); return
    }
    _poll(start.metrics_id, metricKey)
  }

  function _poll(runId, metricKey) {
    const row = rows[metricKey]
    const tick = async () => {
      let st
      try { st = await api.poll(runId) } catch (e) {
        _fail(row, 'Poll failed: ' + (e?.message || 'error')); return
      }
      _setBar(row, st.progress ?? 0)
      const eta = st.eta_s != null ? ` · ~${_fmtEta(st.eta_s)} left` : ''
      const frames = st.frames_total ? ` (${st.frames_done || 0}/${st.frames_total} frames)` : ''
      if (st.state === 'running') {
        _setStatus(row, `Computing${frames}${eta}…`)
        _pollTimer = setTimeout(tick, POLL_MS); return
      }
      _runningMetric = null
      if (st.state === 'error') { _fail(row, 'Error: ' + (st.error || 'unknown')); return }
      const result = st.result
      if (!result?.ready) {
        _setBar(row, null)
        _setStatus(row, result?.reason || 'No data produced.', '#d29922')
        _updateButtons(); return
      }
      _cache[result.scope || _scope()] = result
      _setBar(row, 1)
      const n = result[metricKey]?.temporal?.per_frame?.length || 0
      _setStatus(rows[metricKey], `Ready — ${n} frames, ${result.jobs.length} job(s). ` +
        'All three metrics computed.', '#3fb950')
      // The single pass produced every metric — reflect that on the other rows too.
      for (const { key } of METRICS) if (key !== metricKey && _cache[_scope()]?.[key]) {
        if (!rows[key].status.textContent || rows[key].status.dataset.stale) {
          _setStatus(rows[key], 'Ready (computed with the last run).', '#3fb950')
        }
      }
      _updateButtons()
    }
    tick()
  }

  function _fail(row, msg) {
    _runningMetric = null
    _setBar(row, null)
    _setStatus(row, msg, '#f85149')
    _updateButtons()
  }

  function _display(metricKey) {
    const result = _cache[_scope()]
    if (!result?.ready) return
    openMetricGraphPopup({
      metric: metricKey, result, scope: result.scope || _scope(),
      onExport: () => _export(metricKey),
    })
  }

  async function _export(metricKey) {
    const result = _cache[_scope()]
    if (!result?.ready) return
    const choice = await openMetricExportModal()
    if (!choice) return
    const kinds = exportChoiceFiles(choice)
    const base = `${metricKey}_${result.scope || _scope()}`
    if (kinds.includes('png')) {
      const specs = metricSpecs(metricKey, result, result.scope || _scope())
      downloadHref(`${base}_spatial.png`, renderToDataURL(specs.spatial))
      downloadHref(`${base}_temporal.png`, renderToDataURL(specs.temporal))
    }
    if (kinds.includes('data')) {
      const csv = metricCSVs(result, metricKey)
      downloadText(`${base}_temporal.csv`, csv.temporal)
      downloadText(`${base}_spatial.csv`, csv.spatial)
    }
  }

  // Wire.
  for (const { key } of METRICS) {
    rows[key].gen?.addEventListener('click', () => _generate(key))
    rows[key].disp?.addEventListener('click', () => _display(key))
    rows[key].exp?.addEventListener('click', () => _export(key))
  }
  scopeLatest?.addEventListener('change', _updateButtons)
  scopeChain?.addEventListener('change', _updateButtons)
  _updateButtons()

  /** Called by the panel when the design changes → cached results are stale. */
  function refresh() {
    _cache.latest = null; _cache.chain = null
    for (const { key } of METRICS) {
      _setBar(rows[key], null)
      if (rows[key].status) rows[key].status.dataset.stale = '1'
    }
    _updateButtons()
  }

  return { refresh, _generate, _display, _export }   // last three exposed for tests
}

function _fmtEta(s) {
  if (s < 60) return `${Math.round(s)}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

export { METRIC_META }
