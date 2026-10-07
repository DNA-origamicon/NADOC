/** Read-only readiness refresh shared by the desktop and cadnano hosts. */
export function readinessTarget(state, mode = '3d') {
  const assembly = mode !== 'cadnano' && !!state.assemblyActive
  const document = assembly ? state.currentAssembly : mode === 'cadnano' ? state.design : state.currentDesign
  const populated = assembly
    ? document?.instances?.length
    : document?.helices?.length || document?.strands?.length
  return populated ? { document, assembly } : null
}

function sameTarget(a, b) {
  return a?.document === b?.document && a?.assembly === b?.assembly
}

export function initDesignReadinessController({
  store, widget, fetchReport, mode = '3d', decorate = report => report,
  onReport = () => {}, document = globalThis.document, window = globalThis.window,
  debounceMs = 200, pollMs = 10000,
}) {
  let disposed = false
  let generation = 0
  let request = null
  let debounce = null
  let poll = null
  let target = readinessTarget(store.getState(), mode)
  let report = null
  let renderedSignature = null

  function clearTimers() {
    clearTimeout(debounce)
    clearTimeout(poll)
    debounce = poll = null
  }

  function cancelRequest() {
    generation++
    request?.abort()
    request = null
  }

  function schedulePoll() {
    clearTimeout(poll)
    if (!disposed && target && !document.hidden) poll = setTimeout(() => refresh(), pollMs)
  }

  async function refresh() {
    if (disposed || !target || document.hidden) return
    clearTimers()
    cancelRequest()
    const version = generation
    const requestedTarget = target
    const abort = new AbortController()
    request = abort
    try {
      const next = await fetchReport(requestedTarget, { signal: abort.signal })
      if (disposed || version !== generation || !sameTarget(requestedTarget, readinessTarget(store.getState(), mode))) return
      report = next
      const decorated = decorate(next)
      const signature = JSON.stringify(decorated)
      if (signature !== renderedSignature) {
        widget.setReport(decorated)
        renderedSignature = signature
      }
      onReport(next)
    } catch (error) {
      if (disposed || version !== generation || error?.name === 'AbortError') return
      report = null
      renderedSignature = null
      widget.setError(error?.message || 'Readiness could not be checked. Try again shortly.')
    } finally {
      if (!disposed && version === generation) {
        request = null
        schedulePoll()
      }
    }
  }

  function invalidate() {
    clearTimers()
    cancelRequest()
    report = null
    renderedSignature = null
    target = readinessTarget(store.getState(), mode)
    if (!target) {
      widget.setReport(null)
      return
    }
    // Drop any previous green/blue claim synchronously, before a new request.
    widget.setLoading()
    if (!document.hidden) debounce = setTimeout(() => refresh(), debounceMs)
  }

  function wake() {
    if (disposed) return
    const next = readinessTarget(store.getState(), mode)
    if (!sameTarget(target, next)) {
      invalidate()
    } else if (!document.hidden && target) {
      clearTimeout(debounce)
      debounce = setTimeout(() => refresh(), debounceMs)
    }
  }

  function visibilityChanged() {
    if (document.hidden) {
      clearTimers()
      cancelRequest()
    } else {
      wake()
    }
  }

  const unsubscribe = store.subscribe(state => {
    if (!sameTarget(target, readinessTarget(state, mode))) invalidate()
  })
  window.addEventListener('focus', wake)
  window.addEventListener('nadoc:sim-jobs-changed', wake)
  document.addEventListener('visibilitychange', visibilityChanged)
  invalidate()

  return {
    refresh: wake,
    getReport: () => report,
    dispose() {
      disposed = true
      clearTimers()
      cancelRequest()
      unsubscribe?.()
      window.removeEventListener('focus', wake)
      window.removeEventListener('nadoc:sim-jobs-changed', wake)
      document.removeEventListener('visibilitychange', visibilityChanged)
    },
  }
}
