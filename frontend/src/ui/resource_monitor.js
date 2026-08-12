/**
 * resource_monitor.js — the live "System monitor" sub-section of each simulation
 * engine's Graphs-and-Metrics card: a toggle that reveals three minigraphs (CPU,
 * GPU, RAM utilisation) fed by polling the whole-machine `GET /system/resources`
 * snapshot a few times a second and buffering it client-side into rolling sparklines.
 *
 * Live-only (nothing persisted), whole-machine, local host.  Purely a display-layer
 * readout — it never touches any design (Three-Layer Law).
 *
 * Factory: `initResourceMonitor({ idPrefix, poll })`.
 *   - `idPrefix` — DOM id namespace, matching the card: `${idPrefix}-resources-toggle`,
 *     `${idPrefix}-res-{cpu,gpu,ram}-spark` (canvas) + `-val` (label).
 *   - `poll`     — `() → sample` (defaults to the API client).  Injectable for tests.
 *
 * Owns its poll timer + three ring buffers; polls ONLY while its toggle is open and
 * the tab is visible (so an idle background tab makes no `nvidia-smi` calls).
 */

import { getSystemResources } from '../api/client.js'
import { drawSparkline } from './sparkline.js'

const MAX_POINTS = 90          // rolling window of samples kept per line
const POLL_MS = 1500           // ~0.7 Hz — smooth enough, cheap on nvidia-smi

// Panels can be re-initialised after a document/panel rebuild while their DOM nodes
// survive.  Keep one owner per id namespace so an abandoned timer cannot continue
// issuing invisible requests (or stack another click listener on the same toggle).
const ACTIVE_MONITORS = new Map()

// One line per resource: buffer key, DOM token, sparkline colour.
const LINES = [
  { key: 'cpu', tok: 'cpu', color: '#58a6ff', pct: s => s?.cpu_pct },
  { key: 'gpu', tok: 'gpu', color: '#3fb950', pct: s => s?.gpu_pct },
  { key: 'ram', tok: 'ram', color: '#bc8cff', pct: s => s?.ram_pct },
]

export function initResourceMonitor({ idPrefix, poll = null } = {}) {
  ACTIVE_MONITORS.get(idPrefix)?.stop()
  const toggle = document.getElementById(`${idPrefix}-resources-toggle`)
  const body = document.getElementById(`${idPrefix}-resources-body`)
  if (!toggle || !body) return { stop() {} }
  const arrow = document.getElementById(`${idPrefix}-resources-arrow`)

  const lines = LINES.map(l => ({
    ...l,
    canvas: document.getElementById(`${idPrefix}-res-${l.tok}-spark`),
    val: document.getElementById(`${idPrefix}-res-${l.tok}-val`),
    buf: [],
  }))

  let _open = false
  let _timer = null
  let _inflight = false
  body.style.display = 'none'                 // own the collapsed start (don't rely on HTML)

  const _visible = () => (typeof document === 'undefined' || !document.hidden)
  const _shouldPoll = () => _open && _visible()

  function _syncPolling() {
    if (_shouldPoll()) _startTimer()
    else _stopTimer()
  }

  function _startTimer() {
    if (_timer) return
    _tick()                                  // immediate first sample, no 1.5 s wait
    _timer = setInterval(_tick, POLL_MS)
  }

  function _stopTimer() {
    if (_timer) { clearInterval(_timer); _timer = null }
  }

  async function _tick() {
    if (_inflight) return
    _inflight = true
    // Resolve the client fn lazily (not in the default param) so merely constructing a
    // card whose resource-DOM isn't mounted never reads the import — keeps factory tests
    // that partially-mock the API client from tripping on a missing export.
    const fn = poll || getSystemResources
    let sample = null
    try { sample = await fn() } catch { sample = null } finally { _inflight = false }
    if (_open) _apply(sample)                 // draw even if a stale tick lands
  }

  /** Push one sample into every ring buffer, refresh labels, redraw the sparklines. */
  function _apply(sample) {
    for (const line of lines) {
      const v = line.pct(sample)
      line.buf.push(Number.isFinite(v) ? v : null)
      if (line.buf.length > MAX_POINTS) line.buf.shift()
      if (line.val) line.val.textContent = _label(line.key, sample)
      _draw(line)
    }
  }

  function _draw(line) {
    const c = line.canvas
    if (!c) return
    // Match the backing store to the CSS box so the line is crisp in a narrow panel.
    const cw = c.clientWidth || c.width
    if (cw && c.width !== cw) c.width = cw
    drawSparkline(c, line.buf, { color: line.color, min: 0, max: 100 })
  }

  const _onToggle = () => {
    _open = !_open
    body.style.display = _open ? '' : 'none'
    if (arrow) arrow.style.transform = _open ? 'rotate(90deg)' : ''
    _syncPolling()
  }
  toggle.addEventListener('click', _onToggle)
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', _syncPolling)
  }

  function stop() {
    _stopTimer()
    _open = false
    toggle.removeEventListener('click', _onToggle)
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', _syncPolling)
    }
    if (ACTIVE_MONITORS.get(idPrefix)?.stop === stop) ACTIVE_MONITORS.delete(idPrefix)
  }

  const monitor = { stop, _apply, _tick, _lines: lines }
  ACTIVE_MONITORS.set(idPrefix, monitor)
  return monitor                                  // last three exposed for tests
}

/** Human label for a line: "52%" for CPU, "100% · 6.3/12.0 GB" for GPU/RAM, "n/a"
 *  when the value is missing (e.g. GPU on a CPU-only box). */
function _label(key, s) {
  if (!s) return '…'
  if (key === 'cpu') return _pct(s.cpu_pct)
  if (key === 'gpu') {
    if (!s.gpu_present) return 'n/a'
    return `${_pct(s.gpu_pct)}${_mem(s.vram_used_mb, s.vram_total_mb)}`
  }
  return `${_pct(s.ram_pct)}${_mem(s.ram_used_mb, s.ram_total_mb)}`
}

function _pct(v) { return Number.isFinite(v) ? `${Math.round(v)}%` : 'n/a' }

function _mem(usedMb, totalMb) {
  if (!Number.isFinite(usedMb) || !Number.isFinite(totalMb) || totalMb <= 0) return ''
  return ` · ${(usedMb / 1024).toFixed(1)}/${(totalMb / 1024).toFixed(1)} GB`
}

export { _label as _resourceLabel }
