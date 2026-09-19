import { recordProcess } from './process_log.js'
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
  recordProcess(`operation:${trace.id}`, { label, kind: 'Design operation', startedAt: trace.startedAt })
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
    recordProcess(`operation:${trace.id}`, {
      durationMs: trace.totalMs,
      status: trace.marks.some(mark => ['operation-failed', 'operation-rejected'].includes(mark.name)) ? 'Failed' : 'Completed',
      detail: trace.marks.map((mark, i) => `${mark.name}: +${(mark.elapsedMs - (trace.marks[i - 1]?.elapsedMs ?? 0)).toFixed(1)} ms (${mark.elapsedMs.toFixed(1)} ms total)`).join('\n'),
    })
    _history.push(trace)
    if (_history.length > MAX_HISTORY) _history.shift()
    if (_active === trace) _active = null
    if (!_active) {
      for (const resolve of _idleWaiters) resolve()
      _idleWaiters.clear()
    }
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('nadoc:operation-timing', {
        detail: {
          id: trace.id, label: trace.label, totalMs: trace.totalMs,
          marks: trace.marks.map(({ name, elapsedMs, data }) => ({
            name, elapsedMs, ...(data === undefined ? {} : { data }),
          })),
        },
      }))
    }
    if (trace.totalMs >= SLOW_MS || globalThis.__nadocOperationTraceAll) {
      const rows = trace.marks.map((mark, i) => ({
        phase: mark.name,
        elapsed_ms: Math.round(mark.elapsedMs * 10) / 10,
        delta_ms: Math.round((mark.elapsedMs - (trace.marks[i - 1]?.elapsedMs ?? 0)) * 10) / 10,
        details: mark.data ? JSON.stringify(mark.data) : '',
      }))
      // The paste-friendly one-line phase dump is intentionally opt-in; normal
      // sessions get only the collapsed slow-operation summary below.
      if (globalThis.__nadocOperationTraceAll) {
        console.log(`[operation phases] ${rows.map(r => `${r.phase} +${r.delta_ms}ms${r.details ? ` ${r.details}` : ''}`).join(' | ')}`)
      }
      console.groupCollapsed(`[operation ${Math.round(trace.totalMs)}ms] ${trace.label}`)
      console.table(rows)
      console.groupEnd()
    }
  }))
}

export function activeOperationTiming() { return _active }

/** Briefly defer background polls while an interactive operation renders.
 * Timing is diagnostic, not a lock: an aborted render or a missing completion
 * callback must never prevent unrelated requests from being sent indefinitely.
 * Expiry releases only the waiter; it does not finish or cancel the operation.
 *
 * Deliberately NOT raised for the multi-second design-load case this also now
 * covers (GET /design + GET /design/geometry): every current caller is a
 * periodic timer (job lists, peer status, MD queue, feature-log backfill)
 * running independently of any others, so a longer cap doesn't stagger their
 * releases — it bunches them, since they all resolve together the instant the
 * long operation finishes or the cap expires, trading frequent small bursts
 * for rarer, larger ones. Measured A/B on a live server: raising this to 20s
 * did not reliably improve — and sometimes worsened — a load's wall-clock time.
 * The actual dominant cost turned out to be design_disk_usage.py's directory-
 * walk cache TTL, not this cap; see its own comment. */
export function whenOperationIdle({ maxWaitMs = 2000 } = {}) {
  if (!_active) return Promise.resolve()
  return new Promise(resolve => {
    const release = () => {
      clearTimeout(timer)
      _idleWaiters.delete(release)
      resolve()
    }
    const timer = setTimeout(release, maxWaitMs)
    _idleWaiters.add(release)
  })
}

_expose()
