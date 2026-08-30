/**
 * Alpine GPU availability — the "GPU availability" button in the Clusters card and
 * the popup it opens.
 *
 * Answers the question the submit-review card cannot: of Alpine's GPU partitions
 * (aa100, ami100, al40, and the 2026 ah200 / artxpro6000 additions), which has GPUs
 * free right now, how deep is the queue in front of you, and — for the selected
 * prepared job — which one gets you a finished run soonest.
 *
 * Pure formatting/markup lives in `cluster_availability_rows.js` (separately
 * tested); this factory owns only the DOM, the fetch, and the refresh timer.
 *
 * Refresh policy mirrors `resource_monitor.js`: poll only while the popup is open
 * AND the tab is visible, with an in-flight guard. Alpine login nodes are shared
 * infrastructure — the backend also caches each probe for 60 s, so an idle popup
 * costs the cluster nothing.
 */

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import { getClusterAvailability } from '../api/client.js'
import {
  availabilityHeader,
  availabilityMessage,
  bestPartitionHint,
  renderAvailabilityRows,
  renderSchedulerWarning,
} from './cluster_availability_rows.js'

const REFRESH_MS = 60_000

/**
 * @param {object}   deps
 * @param {Element}  deps.mount        container inside the Clusters card
 * @param {Function} deps.fetchAvailability  (opts) => Promise<resp> (injectable for tests)
 * @param {Function} deps.getJobId     () => selected MD job id (or null) — shapes the estimate
 * @param {object}   deps.timers       { set, clear } (injectable for tests)
 * @param {Document} deps.doc          injectable for tests
 */
export function initClusterAvailability({
  mount,
  fetchAvailability = getClusterAvailability,
  getJobId = () => null,
  timers = { set: setInterval, clear: clearInterval },
  doc = document,
} = {}) {
  let _resp = null
  let _error = ''
  let _busy = false
  let _modal = null
  let _bodyEl = null
  let _timer = null
  let _inflight = false
  let _connected = false

  // ── data ─────────────────────────────────────────────────────────────────
  async function refresh({ force = false } = {}) {
    if (_inflight) return _resp
    _inflight = true
    _busy = true
    _renderBody()
    try {
      _resp = await fetchAvailability({ jobId: getJobId(), force })
      _error = _resp ? '' : 'Could not reach the backend.'
    } catch (err) {
      _resp = null
      // 409 = no live SSH session. That is a normal state, not a failure — say so
      // in the words the user can act on rather than surfacing a status code.
      _error = /409/.test(String(err?.message || err))
        ? 'Not connected to Alpine — connect in the Clusters card first.'
        : `Could not query Alpine: ${err?.message || err}`
    } finally {
      _inflight = false
      _busy = false
      _renderBody()
      _renderButton()
    }
    return _resp
  }

  // ── popup ────────────────────────────────────────────────────────────────
  function _renderBody() {
    if (!_bodyEl) return
    const rows = _resp ? renderAvailabilityRows(_resp.partitions) : ''
    const hint = _resp ? bestPartitionHint(_resp.partitions) : ''
    const scheduler = _resp ? renderSchedulerWarning(_resp) : ''
    const msg = availabilityMessage(_resp, { busy: _busy, error: _error })
    _bodyEl.innerHTML = `
      ${scheduler ? `<div style="margin-bottom:10px">${scheduler}</div>` : ''}
      ${
        hint
          ? `<div style="margin-bottom:10px;padding:7px 10px;border-radius:5px;
               background:rgba(63,185,80,.12);border:1px solid rgba(63,185,80,.35);
               color:#3fb950;font-size:12px">${hint}</div>`
          : ''
      }
      ${
        rows
          ? `<div style="border:1px solid #30363d;border-radius:5px;overflow:hidden">
               ${availabilityHeader()}
               <div style="max-height:340px;overflow-y:auto;font-size:11px">${rows}</div>
             </div>`
          : ''
      }
      ${
        msg
          ? `<div style="font-size:10px;color:#6e7681;margin-top:9px;line-height:1.5">${msg}</div>`
          : ''
      }
      <div style="font-size:10px;color:#6e7681;margin-top:6px;line-height:1.5">
        Wait estimates combine three independent signals — GPUs idle now, SLURM's own
        backfill prediction for this job, and the median of recent jobs. Hover a wait to
        see which one it came from. “unknown” means SLURM could not place the job; it does
        not mean zero.
      </div>
    `
  }

  async function open() {
    if (_modal && _modal.isOpen()) return
    _bodyEl = el('div')
    _modal = createModal({
      title: 'Alpine GPU availability',
      size: 'xl',
      body: _bodyEl,
      // createModal invokes onClose before it detaches the overlay and changes isOpen().
      // Drop our references first so polling stops immediately and an in-flight refresh
      // cannot keep rendering into (or otherwise retain) the popup after its X is clicked.
      onClose: () => {
        _modal = null
        _bodyEl = null
        _syncPolling()
      },
    })
    _renderBody()
    _modal.actions.append(
      createButton({ label: 'Re-check', onClick: () => refresh({ force: true }) }),
      createButton({ label: 'Close', variant: 'primary', onClick: () => _modal.close() }),
    )
    _modal.open()
    await refresh()
    _syncPolling()
  }

  // ── polling: only while the popup is open and the tab is visible ─────────
  const _shouldPoll = () => !!(_modal && _modal.isOpen()) && !doc.hidden

  function _syncPolling() {
    const want = _shouldPoll()
    if (want && !_timer) {
      _timer = timers.set(() => { if (_shouldPoll()) refresh() }, REFRESH_MS)
    } else if (!want && _timer) {
      timers.clear(_timer)
      _timer = null
    }
  }

  // ── the button ───────────────────────────────────────────────────────────
  function _renderButton() {
    if (!mount) return
    const disabled = !_connected
    const title = disabled
      ? 'Connect to Alpine first — availability needs a live session'
      : 'Free GPUs, queue depth and estimated wait per partition'
    const scheduler = _connected && _resp ? renderSchedulerWarning(_resp) : ''
    mount.innerHTML = `
      ${scheduler ? `<div style="margin-bottom:6px">${scheduler}</div>` : ''}
      <button id="alpine-availability-btn" ${disabled ? 'disabled' : ''} title="${title}" style="
        font-size:11px;padding:4px 10px;background:#161b22;border:1px solid #30363d;
        color:${disabled ? '#6e7681' : '#c9d1d9'};border-radius:4px;
        cursor:${disabled ? 'default' : 'pointer'}">
        ${_busy ? 'Checking Alpine…' : 'GPU availability'}
      </button>
    `
    mount.querySelector('#alpine-availability-btn')?.addEventListener('click', () => open())
  }

  // The connection chip already polls /api/cluster/status every 15 s and broadcasts
  // this event — subscribe rather than adding a second poll of the same endpoint.
  const _onClusterState = e => {
    const connected = e?.detail?.state === 'connected'
    const becameConnected = connected && !_connected
    _connected = connected
    if (!connected) { _resp = null; _error = '' }
    _renderButton()
    // One read-only sync per login makes maintenance visible in the Cluster card
    // without requiring the user to discover and open the availability popup.
    if (becameConnected) void refresh()
  }
  window.addEventListener('nadoc:cluster-state-change', _onClusterState)
  const _onVisibility = () => _syncPolling()
  doc.addEventListener('visibilitychange', _onVisibility)

  _renderButton()

  return {
    open,
    refresh,
    get response() { return _resp },
    dispose() {
      window.removeEventListener('nadoc:cluster-state-change', _onClusterState)
      doc.removeEventListener('visibilitychange', _onVisibility)
      if (_timer) { timers.clear(_timer); _timer = null }
      if (_modal && _modal.isOpen()) _modal.close()
      _modal = null
      _bodyEl = null
    },
  }
}
