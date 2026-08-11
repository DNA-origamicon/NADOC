/** End-to-end timing for interactive design operations.
 *
 * Traces are intentionally cheap and always available. Slow operations are logged
 * automatically; set `window.__nadocOperationTraceAll = true` to log every one.
 * Recent measurements are exposed at `window.__nadocOperationTimings`.
 */
const SLOW_MS = 250
const MAX_HISTORY = 50
let _nextId = 1
let _active = null
const _history = []
const _idleWaiters = new Set()

function _now() {
  return globalThis.performance?.now?.() ?? Date.now()
}

function _expose() {
  if (typeof window === 'undefined') return
  window.__nadocOperationTimings = _history
  window.__nadocOperationTiming = {
    recent: () => _history.slice(),
    clear: () => { _history.length = 0 },
  }
}

export function beginOperationTiming(label, details = {}) {
  const trace = {
    id: _nextId++, label, details, startedAt: _now(), marks: [], finished: false,
  }
  // UI operations are serialized in normal use. If one overlaps, retain both in
  // history but make the newest operation the render-completion candidate.
  _active = trace
  trace.marks.push({ name: 'operation-start', at: trace.startedAt, elapsedMs: 0 })
  return trace
}

export function markOperationTiming(name, data = undefined, trace = _active) {
  if (!trace || trace.finished) return
  const at = _now()
  trace.marks.push({ name, at, elapsedMs: at - trace.startedAt, ...(data === undefined ? {} : { data }) })
}

export function finishOperationAfterRender(trace = _active) {
  if (!trace || trace.finished || trace.renderScheduled) return
  trace.renderScheduled = true
  const raf = globalThis.requestAnimationFrame ?? ((cb) => setTimeout(() => cb(_now()), 0))
  // First frame presents the newly rebuilt scene; the second callback confirms
  // that frame has passed through the browser's render loop.
  raf(() => raf(() => {
    if (trace.finished) return
    markOperationTiming('final-render', undefined, trace)
    trace.finished = true
    trace.totalMs = _now() - trace.startedAt
    _history.push(trace)
    if (_history.length > MAX_HISTORY) _history.shift()
    if (_active === trace) _active = null
    if (!_active) {
      for (const resolve of _idleWaiters) resolve()
      _idleWaiters.clear()
    }
    if (trace.totalMs >= SLOW_MS || globalThis.__nadocOperationTraceAll) {
      const rows = trace.marks.map((mark, i) => ({
        phase: mark.name,
        elapsed_ms: Math.round(mark.elapsedMs * 10) / 10,
        delta_ms: Math.round((mark.elapsedMs - (trace.marks[i - 1]?.elapsedMs ?? 0)) * 10) / 10,
      }))
      console.groupCollapsed(`[operation ${Math.round(trace.totalMs)}ms] ${trace.label}`)
      console.table(rows)
      console.groupEnd()
    }
  }))
}

export function activeOperationTiming() { return _active }

/** Resolve after the currently active interactive operation presents its final
 * frame. Display-only background polls use this to avoid stealing CPU/network
 * capacity from click-to-render work. */
export function whenOperationIdle() {
  if (!_active) return Promise.resolve()
  return new Promise(resolve => _idleWaiters.add(resolve))
}

_expose()
