/**
 * Development probe for atomistic reload loops.
 *
 * The persistent toast is a reusable DOM node, so watching only node insertion
 * misses later transitions back to "Loading atomistic model…".  This observer
 * rescans after text and child mutations and records each non-loading → loading
 * transition.  Consumers can attach rendered-position snapshots to each ping.
 */

export const ATOMISTIC_LOADING_PING_EVENT = 'nadoc:atomistic-loading-ping'
export const ATOMISTIC_LOADING_CALL_EVENT = 'nadoc:atomistic-loading-toast-call'
export const ATOMISTIC_LOADING_TEXT = 'Loading atomistic model…'
export const DEFAULT_REPORT_WINDOW_MS = 5_000

function _messages(root) {
  return [...root.querySelectorAll('.toast-message')]
}

function _safeJson(value) {
  const seen = new WeakSet()
  return JSON.stringify(value, (_key, item) => {
    if (typeof item === 'bigint') return `${item}n`
    if (typeof item === 'function') return `[Function ${item.name || 'anonymous'}]`
    if (!item || typeof item !== 'object') return item
    if (seen.has(item)) return '[Circular]'
    seen.add(item)
    return item
  })
}

/**
 * Install an atomistic-loading toast probe.
 *
 * @param {{
 *   root?: Document|Element,
 *   snapshot?: () => unknown,
 *   onPing?: (event: object) => void,
 *   logger?: Pick<Console, 'warn'|'error'|'info'>|null,
 *   now?: () => number,
 *   context?: () => unknown,
 *   reportWindowMs?: number,
 *   autoReport?: boolean,
 * }} options
 * @returns {{count: () => number, events: () => object[], calls: () => object[],
 *            reports: () => object[], latestReport: () => object|null,
 *            forceReport: () => object|null, reset: () => void,
 *            scan: () => void, stop: () => void}}
 */
export function installAtomisticLoadingProbe(options = {}) {
  const root = options.root ?? document
  const view = root.defaultView ?? root.ownerDocument?.defaultView ?? window
  const MutationObserverCtor = view.MutationObserver
  const CustomEventCtor = view.CustomEvent
  const now = options.now ?? (() => view.performance.now())
  const reportWindowMs = options.reportWindowMs ?? DEFAULT_REPORT_WINDOW_MS
  const autoReport = options.autoReport ?? true
  let events = []
  let calls = []
  let reports = []
  let active = new Set()
  let stopped = false
  let windowStartMs = null
  let reportTimer = null

  view.__nadocAtomisticLoadingProbeCount =
    (view.__nadocAtomisticLoadingProbeCount ?? 0) + 1

  function captureContext() {
    try {
      return { value: options.context?.() ?? null, error: null }
    } catch (error) {
      return { value: null, error: String(error?.stack || error) }
    }
  }

  function beginReportWindow(atMs) {
    if (windowStartMs !== null || stopped) return
    windowStartMs = atMs
    if (autoReport) reportTimer = view.setTimeout(finishReportWindow, reportWindowMs)
  }

  function finishReportWindow() {
    if (windowStartMs === null) return null
    if (reportTimer !== null) view.clearTimeout(reportTimer)
    reportTimer = null
    const startedAtMs = windowStartMs
    const endedAtMs = now()
    const appearances = events.filter(event =>
      event.atMs >= startedAtMs && event.atMs <= endedAtMs)
    const showCalls = calls.filter(call =>
      call.atMs >= startedAtMs && call.atMs <= endedAtMs)
    const context = captureContext()
    const report = Object.freeze({
      schema: 'nadoc-atomistic-loading-diagnostic-v1',
      reportWindowMs,
      startedAtMs,
      endedAtMs,
      appearanceCount: appearances.length,
      showCallCount: showCalls.length,
      appearances,
      showCalls,
      contextAtReport: context.value,
      contextError: context.error,
    })
    reports.push(report)
    windowStartMs = null
    options.logger?.error?.(
      'NADOC_ATOMISTIC_LOADING_DIAGNOSTIC=' + _safeJson(report),
    )
    return report
  }

  function onToastCall(event) {
    if (stopped) return
    const call = Object.freeze({
      sequence: calls.length + 1,
      ...event.detail,
      receivedAtMs: now(),
    })
    calls.push(call)
    beginReportWindow(call.atMs ?? call.receivedAtMs)
    options.logger?.warn?.(
      `[atomistic-loading-probe] showPersistentToast call #${call.sequence}`,
      call,
    )
  }

  function scan() {
    if (stopped) return
    const matching = new Set(_messages(root).filter(el =>
      el.textContent?.trim() === ATOMISTIC_LOADING_TEXT))
    for (const el of matching) {
      if (active.has(el)) continue
      let snapshot = null
      let snapshotError = null
      try {
        snapshot = options.snapshot?.() ?? null
      } catch (error) {
        snapshotError = String(error?.stack || error)
      }
      const previous = events.at(-1)
      const atMs = now()
      const event = Object.freeze({
        count: events.length + 1,
        atMs,
        sincePreviousMs: previous ? atMs - previous.atMs : null,
        message: ATOMISTIC_LOADING_TEXT,
        snapshot,
        snapshotError,
      })
      events.push(event)
      beginReportWindow(event.atMs)
      options.logger?.warn?.(
        `[atomistic-loading-probe] ping #${event.count}`,
        event,
      )
      options.onPing?.(event)
      root.dispatchEvent?.(new CustomEventCtor(ATOMISTIC_LOADING_PING_EVENT, {
        detail: event,
      }))
    }
    active = matching
  }

  const observer = new MutationObserverCtor(scan)
  const observeTarget = root.nodeType === 9 ? root.documentElement : root
  observer.observe(observeTarget, {
    childList: true,
    subtree: true,
    characterData: true,
  })
  view.addEventListener(ATOMISTIC_LOADING_CALL_EVENT, onToastCall)
  scan()

  return {
    count: () => events.length,
    events: () => events.slice(),
    calls: () => calls.slice(),
    reports: () => reports.slice(),
    latestReport: () => reports.at(-1) ?? null,
    forceReport: finishReportWindow,
    reset() {
      if (reportTimer !== null) view.clearTimeout(reportTimer)
      reportTimer = null
      windowStartMs = null
      events = []
      calls = []
      reports = []
      active = new Set(_messages(root).filter(el =>
        el.textContent?.trim() === ATOMISTIC_LOADING_TEXT))
    },
    scan,
    stop() {
      stopped = true
      if (reportTimer !== null) view.clearTimeout(reportTimer)
      reportTimer = null
      observer.disconnect()
      view.removeEventListener(ATOMISTIC_LOADING_CALL_EVENT, onToastCall)
      view.__nadocAtomisticLoadingProbeCount = Math.max(
        0, (view.__nadocAtomisticLoadingProbeCount ?? 1) - 1,
      )
      active.clear()
    },
  }
}
