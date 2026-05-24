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

const HEALTH_URL       = '/api/health'
const POLL_OK_MS       = 5000   // steady-state poll cadence
const POLL_RETRY_MS    = 1500   // faster cadence while reconnecting
const FETCH_TIMEOUT_MS = 4000   // a hung backend fails the probe this fast

let _status = 'connected'        // 'connected' | 'reconnecting'
let _serverInstanceId = null
let _health = null
let _timer = null
let _probing = false
let _started = false
const _subs = new Set()

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
  if (_status !== 'reconnecting') {
    _status = 'reconnecting'
    _emit({ type: 'disconnected' })
  }
}

function _scheduleNext() {
  clearTimeout(_timer)
  const delay = _status === 'reconnecting' ? POLL_RETRY_MS : POLL_OK_MS
  _timer = setTimeout(_probe, delay)
}

/** Begin polling. Idempotent. Pass `onChange` to subscribe in the same call. */
export function start({ onChange } = {}) {
  if (onChange) subscribe(onChange)
  if (_started) return
  _started = true
  _probe()
}

/**
 * Called by API fetch wrappers when a request hits a network-level error, so we
 * flip to reconnecting immediately instead of waiting for the next scheduled
 * poll. Probes right away to confirm (and to catch a fast restart).
 */
export function notifyRequestFailure() {
  if (!_started) return
  clearTimeout(_timer)
  _probe()
}

/**
 * Called by API fetch wrappers when a request succeeds. Cheap no-op unless we
 * thought we were down — then re-probe promptly to refresh health / detect a
 * restart instead of waiting out the retry interval.
 */
export function notifyRequestSuccess() {
  if (!_started) return
  if (_status === 'reconnecting') {
    clearTimeout(_timer)
    _probe()
  }
}
