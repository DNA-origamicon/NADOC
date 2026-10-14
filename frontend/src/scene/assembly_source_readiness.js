/** Wait for renderer-owned source data without starting competing base Design reads. */
export function initAssemblySourceReadiness({ isReady }) {
  const pending = new Set()
  let failure = null
  const aborted = () => new DOMException('Assembly loading was superseded.', 'AbortError')

  function whenReady(assembly, { signal } = {}) {
    if (signal?.aborted) return Promise.reject(signal.reason ?? aborted())
    if (isReady(assembly)) return Promise.resolve()
    if (failure) return Promise.reject(failure)
    return new Promise((resolve, reject) => {
      const entry = { assembly, finish }
      const onAbort = () => finish(signal.reason ?? aborted())
      function finish(error) {
        pending.delete(entry)
        signal?.removeEventListener('abort', onAbort)
        if (error) reject(error)
        else resolve()
      }
      pending.add(entry)
      signal?.addEventListener('abort', onAbort, { once: true })
    })
  }

  function notify() {
    for (const entry of [...pending]) {
      try { if (isReady(entry.assembly)) entry.finish() }
      catch (error) { entry.finish(error) }
    }
  }

  function fail(error) {
    failure = error
    for (const entry of [...pending]) entry.finish(error)
  }

  // Disposal cancels this generation but permits a later renderer rebuild.
  function reset() {
    for (const entry of [...pending]) entry.finish(aborted())
    failure = null
  }

  // Only an explicit renderer retry can make a failed source available again.
  function begin() { failure = null }

  return { whenReady, notify, fail, reset, begin }
}
