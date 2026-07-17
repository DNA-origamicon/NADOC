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
import { shouldTearDownDisplays } from './display_tab_policy.js'
import * as api from '../api/client.js'

const _C = { ok: '#5cb85c', warn: '#e0a800', err: '#d9534f', accent: '#4a9eff', dim: '#8b949e' }

const POLL_MS = 500
const FIELD_PUSH_MS = 150   // throttle live field re-aim POSTs (gizmo drag fires fast)
const RECONFIG_MS = 350     // debounce live recomposition POSTs (engine rebuild is heavy)

/** Pure: a stable "composition signature" of the run elements — what REQUIRES the
 *  live engine to be rebuilt (the floor / field on-off / surface params / anchors).
 *  Deliberately EXCLUDES the field magnitude + direction: those are re-aimed in
 *  place (force.F0/.dir mutation) without a rebuild, so they must not trip a
 *  reconfigure.  Two element sets with the same signature → only a field re-aim is
 *  ever needed; a changed signature → recompose the engine. */
export function reconfigSig(el = {}) {
  const f = el.field, s = el.surface, a = el.anchors || []
  const fieldOn = !!(f?.enabled && f.field_pN > 0)
  const surf = s?.enabled ? { dir: s.dir, off: s.offsetNm, stiff: s.stiff } : null
  const anchors = a.map((x) => JSON.stringify(x)).sort()
  return JSON.stringify({ fieldOn, surf, anchors })
}

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
  ensureJobCurrent = null,
} = {}) {
  const liveBtn   = document.getElementById('oxdna-jobs-live-btn')
  const statusEl  = document.getElementById('oxdna-jobs-live-status')
  if (!liveBtn) return { isOn: () => false, toggle: () => {}, stop: () => {}, onFieldChanged: () => {}, refreshButton: () => {} }

  let _available  = false
  let _availReason = 'checking…'
  let _on         = false
  let _sid        = null
  let _hasField   = false      // is the RUNNING session's field on (→ steerable)?
  let _pollTimer  = null
  let _busy       = false      // start/stop in flight → ignore re-entrant clicks
  let _lastPush   = 0
  let _pushTimer  = null
  let _backend    = null       // active compute backend ('CUDA' | 'CPU')
  let _fellBack   = false      // GPU→CPU fallback popup already shown this session?
  let _sig        = null       // composition signature of the running element set
  let _reconfigTimer = null    // debounce timer for live recomposition POSTs

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

    // Stale-design guard: if the design changed since this job was relaxed, offer to
    // roll the feature log back to the relaxation stage (or cancel) before starting —
    // otherwise the live session resolves current selections against the job's frozen
    // topology and errors.  Delegated to the panel (it owns the job list + roll).
    if (ensureJobCurrent && !(await ensureJobCurrent('a live session'))) return

    // Compose whatever the run cards have enabled (like the "Full Sim" run); any
    // combination is allowed. A field with no anchor drifts the whole structure (COM
    // drift) — the E-field card warns, but the live session is not blocked.
    const el = getRunElements?.() || {}
    const field = el.field
    const surface = el.surface
    const anchors = el.anchors || []
    const hasField = !!(field?.enabled && field.field_pN > 0)

    const body = { job_id: job.job_id }
    if (hasField) body.field = { field_pN: field.field_pN, dir: field.dir }
    if (surface?.enabled) body.surface = {
      dir: surface.dir, offset_nm: surface.offsetNm,
      position_nm: surface.positionNm, stiff: surface.stiff,
    }
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
    _sig = reconfigSig(el)   // baseline composition — later changes recompose the run
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

  // A run-card changed while Live is running (field/floor/anchors). If the
  // COMPOSITION changed (floor or field toggled on/off, surface params, anchors) the
  // engine must be rebuilt with the new forces — recompose it over the current pose.
  // If only the field magnitude/direction changed, re-aim it in place (cheap).
  function onElementsChanged() {
    if (!_on || !_sid) return
    const el = getRunElements?.() || {}
    const sig = reconfigSig(el)
    if (sig !== _sig) { _onCompositionChanged(el, sig); return }
    _maybeReaimField(el.field)
  }
  // Back-compat alias (the E-field card wires this name).
  const onFieldChanged = onElementsChanged

  // Re-aim the running field when the gizmo/inputs change (throttled — drag fires
  // many times per second; the backend coalesces to the latest anyway).
  function _maybeReaimField(field) {
    if (!_hasField) return                     // only a session whose field is on is steerable
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

  // The element set changed → recompose the running engine (seamless: it continues
  // from the current live pose).  Debounced — a slider drag fires many changes and an
  // engine rebuild is heavy.  A field with no anchor drifts the whole structure (the
  // E-field card warns), but the recompose is not blocked.
  function _onCompositionChanged(el, sig) {
    const field = el.field
    const hasField = !!(field?.enabled && field.field_pN > 0)
    _sig = sig
    _hasField = hasField
    if (_reconfigTimer) clearTimeout(_reconfigTimer)
    _reconfigTimer = setTimeout(() => { if (_on && _sid) _sendReconfigure(el) }, RECONFIG_MS)
  }

  async function _sendReconfigure(el) {
    const field = el.field, surface = el.surface, anchors = el.anchors || []
    const body = {}
    if (field?.enabled && field.field_pN > 0) body.field = { field_pN: field.field_pN, dir: field.dir }
    if (surface?.enabled) body.surface = {
      dir: surface.dir, offset_nm: surface.offsetNm,
      position_nm: surface.positionNm, stiff: surface.stiff,
    }
    if (anchors.length) body.anchors = anchors
    _setStatus('Updating live run…', _C.accent)
    const r = await api.reconfigureOxdnaLive(_sid, body).catch(() => null)
    if (!_on || !_sid) return
    if (!r?.ok) {
      _setStatus(api.lastErrorMessage?.() || 'Live update failed (see console)', _C.err)
      return
    }
    _setStatus(body.field ? 'Live · field steering — drag to re-aim.'
                          : (body.surface ? 'Live · surface applied.' : 'Live running.'), _C.ok)
  }

  // Clear local state + restore the model overlay (no stop POST — used when the
  // backend already reports the session gone).
  function _teardownLocal() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
    if (_pushTimer) { clearTimeout(_pushTimer); _pushTimer = null }
    if (_reconfigTimer) { clearTimeout(_reconfigTimer); _reconfigTimer = null }
    const wasOn = _on
    _on = false
    _sid = null
    _hasField = false
    _sig = null
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
  // Leaving the Dynamics tab or switching design → stop the live session. The
  // view-only tabs (Photo) are exempt: they render the live frames as-is.
  window.addEventListener('nadoc:left-tab-change', (e) => {
    if (shouldTearDownDisplays(e.detail?.activeTab) && _on) stop()
  })
  window.addEventListener('nadoc:workspace-path-change', () => { if (_on) stop() })

  _checkAvailable()
  _setButton()

  return { isOn: () => _on, toggle, stop, onElementsChanged, onFieldChanged, refreshButton }
}
