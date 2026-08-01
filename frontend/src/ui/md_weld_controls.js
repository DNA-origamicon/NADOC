/**
 * md_weld_controls.js — the Visualizations card's "Weld pair (CPD)" layer.
 *
 * Turns on scene/cpd_weld_overlay.js for the selected MD job and keeps a live readout of
 * the weld reaction coordinates under the checkbox.  This is the UI half of
 * memory/project_cpd_umbrella_sampling.md: the point is to SEE whether a design's two
 * extra thymines ever get close enough to photo-weld, while scrubbing the trajectory,
 * rather than inferring it from a number afterwards.
 *
 * Most designs have no weld pair at all — only ones with extra bases on a *reciprocal*
 * crossover pair do — so "nothing to show" is the common case and must read as a plain
 * statement, not a failure.
 *
 * The overlay itself is driven from inside the atomistic renderer's applyPositionLerp, so
 * this module never touches coordinates; it only switches the layer on and samples the
 * readout.  Display layer only — never touches topology.
 *
 * Factory: initMdWeldControls({ api, getWeldOverlay }) → { setJob, refresh, dispose }
 */

import { buildChartSpec, drawChart, SERIES_COLORS } from './metric_graph.js'

const LS_KEY = 'nadoc:md:weldPair'
const READOUT_MS = 120
const POLL_MS = 700

/** Axis metadata per traced quantity. */
export const TRACE_META = {
  d: { label: 'C5=C6 midpoint distance', yLabel: 'd (Å)', scale: 10, zeroLine: false },
  eta: { label: 'twist η', yLabel: 'η (deg)', scale: 1, zeroLine: true },
  k: { label: 'KIMMDY propensity', yLabel: 'k', scale: 1, zeroLine: false },
}

/**
 * Chart series for a weld-trace result.
 * PURE.  x is the frame's time in ns (the run's own clock — a frame index would be
 * meaningless once the stride widens).  Distance is converted to Å for display; every
 * other readout in this app is in Å and mixing units on one screen is a bug factory.
 */
export function weldTraceSeries (result, metric = 'd') {
  // Normalise ONCE. Deriving the axis metadata and the data key from the raw argument
  // independently let an unknown metric fall back to distance's scale while still
  // reading k's values — charting k x10 with a "d (Å)" axis.
  const m = TRACE_META[metric] ? metric : 'd'
  const meta = TRACE_META[m]
  const key = m === 'd' ? 'd_nm' : m === 'eta' ? 'eta_deg' : 'k'
  const times = result?.times_ps || []
  return (result?.pairs || []).map((p, i) => ({
    label: p.label,
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    points: (p[key] || []).map((v, j) => [(times[j] ?? j) / 1000, v * meta.scale]),
  })).filter((s) => s.points.length)
}

/**
 * One-line summary per pair: did it ever get close?
 * PURE.  Leads with the minimum, because that is the question — a mean of 11 Å with a
 * single 3.6 Å excursion is a very different design verdict from a flat 11 Å.
 */
export function weldTraceSummary (result) {
  if (!result?.pairs?.length) return ''
  const span = result.n_frames && result.n_total_frames
    ? `${result.n_frames} of ${result.n_total_frames} frames (stride ${result.stride})`
    : `${result.n_frames || 0} frames`
  const lines = result.pairs.map((p) => {
    const reactive = p.reactive_frames
      ? `${p.reactive_frames} reactive`
      : 'never reactive'
    return `${p.label}  min ${(p.d_min_nm * 10).toFixed(2)} Å   `
      + `mean ${(p.d_mean_nm * 10).toFixed(2)} Å   k max ${p.k_max.toFixed(3)}   ${reactive}`
  })
  return [span, ...lines].join('\n')
}

/**
 * Status line for the current pair set.
 * PURE — the "no weld pair" case is the common one and has to read as information, not
 * an error, so it is worth pinning.
 */
export function weldStatusText ({ ready, pairs, reason, enabled } = {}) {
  if (!enabled) return ''
  if (!ready && reason) return reason
  const n = pairs?.length ?? 0
  if (!n) return reason || 'no weld pair in this design'
  return n === 1 ? '1 weld pair' : `${n} weld pairs`
}

/**
 * Readout lines for the HUD under the checkbox.
 * PURE.  Empty array → the readout block is hidden rather than showing a stale value.
 */
export function weldReadoutLines (readouts) {
  if (!readouts?.length) return []
  return readouts.map((r) => (readouts.length === 1 ? r.readout : `${r.label}  ${r.readout}`))
}

export function initMdWeldControls ({ api, getWeldOverlay = null } = {}) {
  const toggle = document.getElementById('md-jobs-weld-toggle')
  const readoutEl = document.getElementById('md-jobs-weld-readout')
  const statusEl = document.getElementById('md-jobs-weld-status')
  if (!toggle) return null

  let _jobId = null
  let _timer = null
  let _last = { ready: false, pairs: [], reason: null }

  const _read = () => { try { return localStorage.getItem(LS_KEY) === 'true' } catch { return false } }
  const _write = (v) => { try { localStorage.setItem(LS_KEY, String(v)) } catch { /* private mode */ } }

  function _setStatus (text, color = '#8b949e') {
    if (statusEl) { statusEl.textContent = text; statusEl.style.color = color }
  }

  function _tick () {
    const lines = weldReadoutLines(getWeldOverlay?.()?.getReadouts?.())
    if (!readoutEl) return
    if (!lines.length) { readoutEl.style.display = 'none'; return }
    readoutEl.style.display = ''
    readoutEl.textContent = lines.join('\n')
  }

  function _startTicking () {
    if (_timer) return
    _timer = setInterval(_tick, READOUT_MS)
  }

  function _stopTicking () {
    if (_timer) { clearInterval(_timer); _timer = null }
    if (readoutEl) readoutEl.style.display = 'none'
  }

  async function _apply () {
    const overlay = getWeldOverlay?.()
    const on = !!toggle.checked
    _write(on)
    if (!overlay) { _setStatus('atomistic view not available'); return }
    if (!on) {
      overlay.setVisible(false)
      _stopTicking()
      _setStatus('')
      return
    }
    if (!_jobId) { _setStatus('select a job first'); return }
    _setStatus('loading…')
    try {
      _last = await overlay.loadForJob(api, _jobId)
    } catch (err) {
      _last = { ready: false, pairs: [], reason: String(err?.message || err) }
    }
    const n = _last.pairs?.length ?? 0
    _setStatus(weldStatusText({ ..._last, enabled: true }), n ? '#8b949e' : '#d29922')
    if (n) _startTicking()
    else _stopTicking()
  }

  toggle.addEventListener('change', () => { _apply() })
  toggle.checked = _read()

  // ── trace over the whole run ────────────────────────────────────────────────
  const traceBtn = document.getElementById('md-jobs-weld-trace-btn')
  const traceMetric = document.getElementById('md-jobs-weld-trace-metric')
  const traceCanvas = document.getElementById('md-jobs-weld-trace-canvas')
  const traceSummary = document.getElementById('md-jobs-weld-trace-summary')
  let _traceResult = null
  let _tracePoll = null

  function _drawTrace () {
    if (!traceCanvas || !_traceResult) return
    const metric = traceMetric?.value || 'd'
    const meta = TRACE_META[metric] ?? TRACE_META.d
    const spec = buildChartSpec({
      series: weldTraceSeries(_traceResult, metric),
      width: traceCanvas.width, height: traceCanvas.height,
      xLabel: 'time (ns)', yLabel: meta.yLabel, zeroLine: meta.zeroLine,
    })
    traceCanvas.style.display = ''
    drawChart(traceCanvas, spec)
    if (traceSummary) {
      traceSummary.style.display = ''
      traceSummary.textContent = weldTraceSummary(_traceResult)
    }
  }

  function _stopPoll () { if (_tracePoll) { clearInterval(_tracePoll); _tracePoll = null } }

  async function runTrace () {
    if (!_jobId) { _setStatus('select a job first'); return }
    if (!api?.startMdCpdTrace) return
    _stopPoll()
    _setStatus('tracing…')
    if (traceBtn) traceBtn.disabled = true
    let started
    try {
      started = await api.startMdCpdTrace(_jobId, { withWindows: !!ladderToggle?.checked })
    } catch (err) {
      _setStatus(String(err?.message || err), '#f85149')
      if (traceBtn) traceBtn.disabled = false
      return
    }
    const id = started?.trace_id
    if (!id) {
      _setStatus('could not start the trace', '#f85149')
      if (traceBtn) traceBtn.disabled = false
      return
    }
    _tracePoll = setInterval(async () => {
      const r = await api.getMdCpdTrace(id).catch(() => null)
      if (!r) return
      if (r.state === 'running') {
        const n = r.frames_total ? ` ${r.frames_done}/${r.frames_total}` : ''
        _setStatus(`tracing…${n}`)
        return
      }
      _stopPoll()
      if (traceBtn) traceBtn.disabled = false
      if (r.state === 'error') { _setStatus(r.error || 'trace failed', '#f85149'); return }
      _traceResult = r.result
      // Fold the seeding verdict into the ladder beads: an unseeded window is one this
      // run cannot start, which is worth seeing BEFORE any GPU time goes into it.
      const seeds = _traceResult?.pairs?.[0]?.seeds
      if (seeds?.length && ladderToggle?.checked) getWeldOverlay?.()?.setWindows?.(seeds)
      if (!_traceResult?.pairs?.length) {
        _setStatus(_traceResult?.reason || 'no weld pair to trace', '#d29922')
        return
      }
      _setStatus(weldStatusText({ ..._last, enabled: true }))
      _drawTrace()
    }, POLL_MS)
  }

  traceBtn?.addEventListener('click', () => { runTrace() })
  traceMetric?.addEventListener('change', () => { _drawTrace() })

  // ── umbrella window ladder (preview only, launches nothing) ─────────────────
  const ladderToggle = document.getElementById('md-jobs-weld-ladder-toggle')

  async function _applyLadder () {
    const overlay = getWeldOverlay?.()
    if (!overlay?.setWindows) return
    if (!ladderToggle?.checked) { overlay.setWindows([]); return }
    if (!_jobId) { _setStatus('select a job first'); return }
    const resp = await api?.getMdCpdColvars?.(_jobId).catch(() => null)
    if (!resp?.windows?.length) {
      overlay.setWindows([])
      _setStatus(resp?.reason || 'no window ladder available', '#d29922')
      return
    }
    overlay.setWindows(resp.windows)
    _setStatus(`${resp.windows.length} umbrella windows `
      + `(${resp.windows[0].center_ang}–${resp.windows[resp.windows.length - 1].center_ang} Å)`)
  }

  ladderToggle?.addEventListener('change', () => { _applyLadder() })

  /** The panel tells us which job is selected; re-resolve the pair set for it. */
  function setJob (jobId) {
    if (jobId === _jobId) return
    _jobId = jobId || null
    getWeldOverlay?.()?.setPairs?.([])
    // A trace belongs to ONE run. Leaving the previous job's chart up while a new job is
    // selected is the worst kind of wrong: it looks like current data.
    _stopPoll()
    _traceResult = null
    if (traceCanvas) traceCanvas.style.display = 'none'
    if (traceSummary) traceSummary.style.display = 'none'
    if (traceBtn) traceBtn.disabled = false
    getWeldOverlay?.()?.setWindows?.([])
    if (ladderToggle?.checked) _applyLadder()
    if (toggle.checked) _apply()
    else _setStatus('')
  }

  function dispose () {
    _stopTicking()
    _stopPoll()
    getWeldOverlay?.()?.setVisible?.(false)
  }

  // Restore the persisted state once a job arrives (setJob drives the first _apply).
  return { setJob, refresh: _apply, runTrace, dispose }
}
