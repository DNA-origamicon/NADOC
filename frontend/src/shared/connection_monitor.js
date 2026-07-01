/**
 * Backend connection monitor — shared by the 3D app and the cadnano editor.
 *
 * Polls GET /api/health on an interval and exposes a small state machine so the
 * UI can show connection status and react to a server restart:
 *
 *   'connected'     — last health probe succeeded
 *   'reconnecting'  — a probe (or an API request) failed; retrying faster
 *
 * Restart detection: /api/health returns a `server_instance_id` that is fresh
 * per backend process. When the id changes, the backend restarted — the monitor
 * fires a `restarted` event so the app can re-sync (the backend's session-cache
 * has already silently restored the document) or fall back to restoring from
 * this tab's localStorage cache if the backend came back empty.
 *
 * No store dependency — usable from either entry point.
 *
 * Events delivered to subscribers ({ type, health?, previousServerInstanceId? }):
 *   'connected'     — first successful probe
 *   'disconnected'  — transitioned to reconnecting
 *   'reconnected'   — came back after a disconnect (same server instance)
 *   'restarted'     — came back with a NEW server instance id
 */

const HEALTH_URL          = '/api/health'
const POLL_OK_MS          = 5000   // idle heartbeat cadence (only when nothing else is talking to the backend)
const POLL_RETRY_MS       = 1500   // faster cadence while a failure is pending / reconnecting
const FETCH_TIMEOUT_MS    = 4000   // a hung backend fails the probe this fast
const FAILURES_BEFORE_DOWN = 2     // tolerate a single blip (e.g. a probe stalled behind a heavy op) before flashing red

let _status = 'connected'        // 'connected' | 'reconnecting'
let _serverInstanceId = null
let _health = null
let _timer = null
let _probing = false
let _started = false
let _consecutiveFailures = 0     // reset on any success; flips to reconnecting at FAILURES_BEFORE_DOWN
const _subs = new Set()

const _hidden = () => typeof document !== 'undefined' && document.hidden

function _emit(evt) {
  for (const cb of _subs) {
    try { cb(evt) } catch (err) { console.error('[conn-monitor] subscriber threw', err) }
  }
}

/** Subscribe to connection events. Returns an unsubscribe function. */
export function subscribe(cb) { _subs.add(cb); return () => _subs.delete(cb) }

export function getStatus() { return _status }
export function getHealth() { return _health }

async function _probe() {
  if (_probing) return
  _probing = true
  const ctrl = new AbortController()
  const to = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS)
  try {
    const r = await fetch(HEALTH_URL, { signal: ctrl.signal, cache: 'no-store' })
    if (!r.ok) throw new Error(`health ${r.status}`)
    const health = await r.json()
    _onHealth(health)
  } catch {
    _onFailure()
  } finally {
    clearTimeout(to)
    _probing = false
    _scheduleNext()
  }
}

function _onHealth(health) {
  _health = health
  _consecutiveFailures = 0
  const prevId = _serverInstanceId
  const newId  = health?.server_instance_id ?? null
  const wasDown = _status === 'reconnecting'

  if (prevId !== null && newId !== null && newId !== prevId) {
    // New backend process — server restarted.
    _serverInstanceId = newId
    _status = 'connected'
    _emit({ type: 'restarted', health, previousServerInstanceId: prevId })
    return
  }
  _serverInstanceId = newId
  if (_status !== 'connected') {
    _status = 'connected'
    _emit({ type: wasDown ? 'reconnected' : 'connected', health })
  } else if (prevId === null) {
    _emit({ type: 'connected', health })
  }
}

function _onFailure() {
  _consecutiveFailures += 1
  // Debounce the down-transition: a single failed probe is often just a probe
  // that stalled behind a heavy backend op, not a real disconnect. Wait for a
  // second consecutive failure (a fast retry happens in between) before flashing
  // red, so legitimate long operations don't trigger a fake "reconnecting…".
  if (_consecutiveFailures < FAILURES_BEFORE_DOWN) return
  if (_status !== 'reconnecting') {
    _status = 'reconnecting'
    _emit({ type: 'disconnected' })
  }
}

function _scheduleNext() {
  clearTimeout(_timer)
  _timer = null
  // Paused while the tab is backgrounded: real traffic resumes on focus, and a
  // hidden tab has nothing to react to. _onVisibilityChange re-probes on re-show.
  if (_hidden()) return
  const pending = _status === 'reconnecting' || _consecutiveFailures > 0
  const delay = pending ? POLL_RETRY_MS : POLL_OK_MS
  _timer = setTimeout(_probe, delay)
}

function _onVisibilityChange() {
  if (!_started) return
  if (_hidden()) {
    clearTimeout(_timer); _timer = null     // stop the idle heartbeat
  } else {
    clearTimeout(_timer); _probe()          // foregrounded — confirm liveness now (catches a restart that happened while hidden)
  }
}

/** Begin polling. Idempotent. Pass `onChange` to subscribe in the same call. */
export function start({ onChange } = {}) {
  if (onChange) subscribe(onChange)
  if (_started) return
  _started = true
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', _onVisibilityChange)
  }
  _probe()
}

/**
 * Called by API fetch wrappers when a request hits a network-level error. Counts
 * as a failure toward the debounce and probes right away to confirm (a second
 * failure then flips to reconnecting; a recovery resets the count → no flicker).
 */
export function notifyRequestFailure() {
  if (!_started) return
  _consecutiveFailures += 1
  clearTimeout(_timer)
  _probe()
}

/**
 * Called by API fetch wrappers on every successful request. A real request IS a
 * liveness signal, so while connected this DEFERS the next idle heartbeat a full
 * interval — during active editing the dedicated /health poll never fires, and it
 * only resumes once the user goes idle. If we thought we were down, re-probe now
 * to refresh health / detect a restart instead of waiting out the retry interval.
 */
export function notifyRequestSuccess() {
  if (!_started) return
  _consecutiveFailures = 0
  if (_status === 'reconnecting') {
    clearTimeout(_timer)
    _probe()
  } else {
    _scheduleNext()   // push the idle heartbeat out — real traffic already proved liveness
  }
}

/**
 * Called when an API request is taking unusually long (the busy popup just fired).
 * Runs a /health probe NOW — which has its own short timeout — so a wedged backend
 * (event loop stuck) surfaces as "reconnecting…" within seconds instead of the user
 * staring at a frozen screen, WITHOUT aborting the slow request itself. A merely
 * busy-but-healthy backend answers /health (heavy work runs off the event loop), so
 * this never false-flags a legitimately long operation.
 */
export function pokeProbe() {
  if (!_started || _probing) return
  clearTimeout(_timer)
  _probe()
}
