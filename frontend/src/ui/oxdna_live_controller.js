/**
 * Live oxDNA controller — the ephemeral "Live" mode of the oxDNA panel
 * (Dynamics tab).
 *
 * Owns the #oxdna-jobs-live-btn toggle.  When turned on it starts an EPHEMERAL
 * in-process oxpy field session (routes_oxdna_live.py) seeded from the selected
 * completed relaxed job — NOTHING is persisted (no job in the list, no stored
 * frames, just a temp oxpy rundir).  It then polls the running session for the
 * current configuration and deforms the NADOC model to it via
 * oxdnaDisplay.displayLiveFrame(...), and on every field change (gizmo drag /
 * input edit) pushes the new direction/magnitude so the running structure
 * responds in (near) real time.
 *
 * Mutual exclusion: starting Live turns off the panel's relaxed/flex/trajectory
 * overlays (they share the one bead overlay) via the `nadoc:oxdna-live-start`
 * event; clicking Relax or Production (or a display toggle) stops Live by calling
 * stop() from the panel.  Display-only — live coordinates are never written into
 * topology (Three-Layer Law).
 *
 * The session composes whatever the run cards have enabled — an electric field, a
 * hard surface, anchors, or none (free dynamics) — exactly like the "Full Sim"
 * run; only a field requires ≥1 anchor.
 *
 * Factory: initOxdnaLive({ oxdnaDisplay, getSelectedJob, getRunElements }) →
 *   { isOn, toggle, stop, onFieldChanged, refreshButton }.  getRunElements() →
 *   { field:{enabled,field_pN,dir}, surface:{enabled,dir,offsetNm,stiff}, anchors[] }.
 */

import { showToast } from './toast.js'
import * as api from '../api/client.js'

const _C = { ok: '#5cb85c', warn: '#e0a800', err: '#d9534f', accent: '#4a9eff', dim: '#8b949e' }

const POLL_MS = 500
const FIELD_PUSH_MS = 150   // throttle live field re-aim POSTs (gizmo drag fires fast)

/** Pure: can a job seed a live session?  A completed ROOT relaxation (not a
 *  field/production child — Live runs on a relaxed structure). */
export function liveJobEligible(job) {
  return job?.status === 'completed' && !job?.parent_job_id
}

/** Pure: gate the Live button.  Returns { enabled, reason } — `reason` is the
 *  disabled tooltip (oxpy missing / no completed relaxed job selected). */
export function liveButtonState({ available, availReason, job }) {
  if (!available) return { enabled: false, reason: availReason || 'oxpy live engine not available' }
  if (!liveJobEligible(job)) {
    return { enabled: false, reason: 'Select a completed relaxed job to run Live on' }
  }
  return { enabled: true, reason: 'Start a live, field-steerable oxDNA session (nothing is saved)' }
}

/** Pure: human label for the active compute backend ('CUDA'→GPU, 'CPU'→CPU). */
export function backendLabel(backend) {
  if (backend === 'CUDA') return 'GPU (CUDA)'
  if (backend === 'CPU')  return 'CPU'
  return ''
}

/** Pure: the running-status line, including the active backend when known. */
export function liveStatusLine({ ready, nPositions = 0, nBursts = 0, backend = null } = {}) {
  if (!ready) return 'Live session warming up…'
  const eng = backendLabel(backend)
  const on  = eng ? ` · ${eng}` : ''
  return `Live · ${nPositions} nt · ${nBursts} burst${nBursts === 1 ? '' : 's'} stepped${on}`
}

/** Pure: one-shot GPU→CPU fallback popup text, or null. `shown` guards the
 *  one-time alert so the per-frame poll doesn't spam it. */
export function liveFallbackNotice(frame, shown) {
  if (shown || !frame?.backend_fell_back) return null
  return 'GPU out of memory — this design is too large for the GPU (or other GPU '
       + 'jobs are using it), so the live session fell back to CPU (slower).'
}

export function initOxdnaLive({
  oxdnaDisplay = null, getSelectedJob = null, getRunElements = null,
} = {}) {
  const liveBtn   = document.getElementById('oxdna-jobs-live-btn')
  const statusEl  = document.getElementById('oxdna-jobs-live-status')
  if (!liveBtn) return { isOn: () => false, toggle: () => {}, stop: () => {}, onFieldChanged: () => {}, refreshButton: () => {} }

  let _available  = false
  let _availReason = 'checking…'
  let _on         = false
  let _sid        = null
  let _hasField   = false      // did this session start WITH a field (→ steerable)?
  let _pollTimer  = null
  let _busy       = false      // start/stop in flight → ignore re-entrant clicks
  let _lastPush   = 0
  let _pushTimer  = null
  let _backend    = null       // active compute backend ('CUDA' | 'CPU')
  let _fellBack   = false      // GPU→CPU fallback popup already shown this session?

  function _setStatus(text, color = _C.dim) {
    if (statusEl) { statusEl.textContent = text; statusEl.style.color = color }
  }

  function _setButton() {
    if (_on) {
      liveBtn.textContent = '■ Stop Live'
      liveBtn.disabled = false
      liveBtn.title = 'Stop the live oxDNA session'
      liveBtn.style.cursor = 'pointer'
      liveBtn.style.background = '#3a1a1a'
      liveBtn.style.borderColor = '#d9534f'
      liveBtn.style.color = '#ff9a9a'
      return
    }
    const { enabled, reason } = liveButtonState({
      available: _available, availReason: _availReason,
      job: getSelectedJob?.() || null,
    })
    liveBtn.textContent = '◉ Live'
    liveBtn.disabled = !enabled || _busy
    liveBtn.title = reason
    liveBtn.style.cursor = enabled ? 'pointer' : 'not-allowed'
    liveBtn.style.background = enabled ? '#2a1a3a' : '#1a1622'
    liveBtn.style.borderColor = enabled ? '#a371f7' : '#30363d'
    liveBtn.style.color = enabled ? '#d2a8ff' : '#484f58'
  }
  function refreshButton() { _setButton() }

  async function _checkAvailable() {
    const d = await api.oxdnaLiveAvailable().catch(() => null)
    _available = !!d?.available
    _availReason = d?.reason || 'oxpy live engine not available'
    _setButton()
  }

  // ── Start / poll / stop ─────────────────────────────────────────────────────
  async function start() {
    if (_busy || _on) return
    const job = getSelectedJob?.() || null
    if (!liveJobEligible(job)) { showToast('Select a completed relaxed job first', 'warn'); return }

    // Compose whatever the run cards have enabled (like the "Full Sim" run); any
    // combination is allowed — only a field requires ≥1 anchor.
    const el = getRunElements?.() || {}
    const field = el.field
    const surface = el.surface
    const anchors = el.anchors || []
    const hasField = !!(field?.enabled && field.field_pN > 0)
    if (hasField && !anchors.length) {
      _setStatus('A field needs ≥1 anchor — add a fixed strand in the Anchors card, or disable the field.', _C.warn)
      showToast('Field needs ≥1 anchor', 'warn'); return
    }

    const body = { job_id: job.job_id }
    if (hasField) body.field = { field_pN: field.field_pN, dir: field.dir }
    if (surface?.enabled) body.surface = { dir: surface.dir, offset_nm: surface.offsetNm, stiff: surface.stiff }
    if (anchors.length) body.anchors = anchors

    _busy = true
    _hasField = hasField
    _setButton()
    _setStatus('Starting live session…', _C.accent)

    const r = await api.startOxdnaLive(body)
    _busy = false
    if (!r?.session_id) {
      _setStatus(api.lastErrorMessage?.() || 'Failed to start live session (see console)', _C.err)
      _setButton()
      return
    }
    _sid = r.session_id
    _on = true
    _backend = r.backend || null
    _fellBack = false
    _setButton()
    // Live now owns the one bead overlay — tell the panel to clear its relaxed /
    // flex / trajectory overlays AND lock those toggles (isOn() is true now, so the
    // panel disables them).  Fires before the first polled frame is applied, so the
    // shared overlay is never fought over.
    window.dispatchEvent(new CustomEvent('nadoc:oxdna-live-start'))
    const eng = backendLabel(_backend)
    const onEng = eng ? ` on ${eng}` : ''
    _setStatus(hasField ? `Live session running${onEng} — drag the field to steer.`
                        : `Live session running${onEng}.`, _C.ok)
    _schedulePoll(0)
  }

  function _schedulePoll(delay = POLL_MS) {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
    _pollTimer = setTimeout(_poll, delay)
  }

  async function _poll() {
    if (!_on || !_sid) return
    const f = await api.getOxdnaLiveFrame(_sid)
    if (!_on || !_sid) return                 // stopped while the request was in flight
    if (!f) {                                  // 404 / session gone → tear down
      _setStatus('Live session ended.', _C.dim)
      _teardownLocal()
      return
    }
    if (f.status === 'error') {
      _setStatus(`Live session error: ${f.error || 'unknown'}`, _C.err)
      stop()
      return
    }
    // GPU→CPU fallback (out of memory): alert the user ONCE, then carry on on CPU.
    const note = liveFallbackNotice(f, _fellBack)
    if (note) {
      _fellBack = true
      showToast(note, { severity: 'warn', duration: 8000 })
    }
    if (f.backend) _backend = f.backend
    if (f.ready && Array.isArray(f.positions) && f.positions.length) {
      oxdnaDisplay?.displayLiveFrame?.(f.positions)
      _setStatus(liveStatusLine({ ready: true, nPositions: f.n_positions,
                                  nBursts: f.n_bursts, backend: _backend }), _C.ok)
    } else {
      _setStatus('Live session warming up…', _C.accent)
    }
    _schedulePoll()
  }

  // Re-aim the running field when the gizmo/inputs change (throttled — drag fires
  // many times per second; the backend coalesces to the latest anyway).
  function onFieldChanged() {
    if (!_on || !_sid || !_hasField) return   // only a session started WITH a field is steerable
    const field = (getRunElements?.() || {}).field
    if (!field?.enabled || !(field.field_pN > 0)) return
    const now = Date.now()
    const send = () => {
      _lastPush = Date.now()
      api.updateOxdnaLiveField(_sid, { field_pN: field.field_pN, dir: field.dir }).catch(() => {})
    }
    if (now - _lastPush >= FIELD_PUSH_MS) { send() }
    else {
      if (_pushTimer) clearTimeout(_pushTimer)
      _pushTimer = setTimeout(() => { if (_on && _sid) send() }, FIELD_PUSH_MS - (now - _lastPush))
    }
  }

  // Clear local state + restore the model overlay (no stop POST — used when the
  // backend already reports the session gone).
  function _teardownLocal() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
    if (_pushTimer) { clearTimeout(_pushTimer); _pushTimer = null }
    const wasOn = _on
    _on = false
    _sid = null
    _hasField = false
    if (oxdnaDisplay?.mode?.() === 'live') oxdnaDisplay.stopAndRestore()
    _setButton()
    // Tell the panel to re-enable the display / flex / trajectory toggles it locked
    // while Live was running (only if it actually was, to avoid spurious churn).
    if (wasOn) window.dispatchEvent(new CustomEvent('nadoc:oxdna-live-stop'))
  }

  function stop() {
    const sid = _sid
    _teardownLocal()
    _setStatus('Live off.', _C.dim)
    if (sid) api.stopOxdnaLive(sid).catch(() => {})   // fire-and-forget teardown
  }

  function toggle() { _on ? stop() : start() }

  liveBtn.addEventListener('click', toggle)

  // The selected job (or its status) changed → re-evaluate the button enable.
  window.addEventListener('nadoc:oxdna-job-selected', () => {
    // Selecting a different job while Live is running invalidates the session.
    if (_on) stop()
    _setButton()
  })
  // Leaving the Dynamics tab or switching design → stop the live session.
  window.addEventListener('nadoc:left-tab-change', (e) => {
    if (e.detail?.activeTab !== 'dynamics' && _on) stop()
  })
  window.addEventListener('nadoc:workspace-path-change', () => { if (_on) stop() })

  _checkAvailable()
  _setButton()

  return { isOn: () => _on, toggle, stop, onFieldChanged, refreshButton }
}
