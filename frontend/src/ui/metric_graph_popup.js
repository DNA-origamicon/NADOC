/**
 * metric_graph_popup.js — the Display popup for the oxDNA Graphs & Metrics card.
 * Shows a metric's SPATIAL (vs position) and TEMPORAL (vs sim time) graphs side by
 * side, annotated with axis labels/units, a zero reference line, and a per-job
 * legend (for the "all parent/child jobs" scope).  Built lazily, reused per open.
 *
 * Display-only: an Export button hands off to the card's export flow via the
 * `onExport` callback (which opens metric_export_modal); this popup never writes.
 */

import { buildChartSpec, drawChart, metricSeries, METRIC_META } from './metric_graph.js'

const CANVAS_W = 560, CANVAS_H = 300

let _root = null, _titleEl = null, _spatial = null, _temporal = null, _exportBtn = null
let _onExport = null

function _build() {
  if (_root) return
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
        <div id="metric-popup-title" style="font-size:15px;font-weight:600"></div>
        <div style="display:flex;gap:8px">
          <button id="metric-popup-export"
            style="padding:5px 12px;background:#21262d;border:1px solid #30363d;
                   border-radius:6px;color:#c9d1d9;cursor:pointer">Export…</button>
          <button id="metric-popup-close"
            style="padding:5px 12px;background:#21262d;border:1px solid #30363d;
                   border-radius:6px;color:#c9d1d9;cursor:pointer">Close</button>
        </div>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:16px;justify-content:center">
        <canvas id="metric-popup-spatial" width="${CANVAS_W}" height="${CANVAS_H}"
                style="background:#0d1117;border:1px solid #21262d;border-radius:4px"></canvas>
        <canvas id="metric-popup-temporal" width="${CANVAS_W}" height="${CANVAS_H}"
                style="background:#0d1117;border:1px solid #21262d;border-radius:4px"></canvas>
      </div>
    </div>`
  document.body.appendChild(overlay)
  _root = overlay
  _titleEl = overlay.querySelector('#metric-popup-title')
  _spatial = overlay.querySelector('#metric-popup-spatial')
  _temporal = overlay.querySelector('#metric-popup-temporal')
  _exportBtn = overlay.querySelector('#metric-popup-export')
  overlay.querySelector('#metric-popup-close').addEventListener('click', close)
  overlay.addEventListener('click', e => { if (e.target === overlay) close() })
  _exportBtn.addEventListener('click', () => _onExport && _onExport())
}

/** Build the two chart specs (spatial + temporal) for a metric result — pure, so
 *  the card can reuse them for PNG export without opening the popup. */
export function metricSpecs(metric, result, scope) {
  const meta = METRIC_META[metric]
  const bp = metric === 'base_pairing'
  const sampleNote = result?.sampling === 'uniform'
    ? ` — ${result.frames_sampled} uniformly sampled of ${result.frames_raw} frames`
    : ''
  return {
    spatial: buildChartSpec({
      series: metricSeries(result, metric, 'spatial'), width: CANVAS_W, height: CANVAS_H,
      title: 'Spatial — vs position along bundle',
      xLabel: meta.spatial.xLabel, yLabel: meta.spatial.yLabel,
      zeroLine: meta.zeroLine, yMin: bp ? 0 : null, yMax: bp ? 1 : null,
    }),
    temporal: buildChartSpec({
      series: metricSeries(result, metric, 'temporal'), width: CANVAS_W, height: CANVAS_H,
      title: (scope === 'chain' ? 'Temporal — vs sim time (jobs concatenated)' : 'Temporal — vs sim time') + sampleNote,
      xLabel: meta.temporal.xLabel, yLabel: meta.temporal.yLabel,
      zeroLine: meta.zeroLine, yMin: bp ? 0 : null, yMax: bp ? 1 : null,
    }),
  }
}

/** Open the popup for `metric` with a metrics-run `result`.  `onExport` is invoked
 *  when the user clicks Export…. */
export function openMetricGraphPopup({ metric, result, scope = 'latest', onExport = null }) {
  _build()
  _onExport = onExport
  const meta = METRIC_META[metric]
  _titleEl.textContent =
    `${meta.label} — ${scope === 'chain' ? 'all parent/child jobs' : 'latest job'}`
  const specs = metricSpecs(metric, result, scope)
  drawChart(_spatial, specs.spatial)
  drawChart(_temporal, specs.temporal)
  _root.style.display = 'flex'
}

export function close() { if (_root) _root.style.display = 'none' }
