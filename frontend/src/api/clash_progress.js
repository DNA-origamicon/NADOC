/** Follow measured check progress in the originating document; cancel obsolete work. */
export async function withClashProgress(headers, run, onProgress, { signal, fetchImpl = fetch, pollMs = 150 } = {}) {
  if (signal?.aborted) return null
  if (!onProgress) return run(undefined, signal)
  const id = crypto.randomUUID(), abort = new AbortController()
  const docHeaders = { ...headers }, path = `/api/design/clashes/progress/${id}`
  let stopped = false, timer
  async function poll() {
    try {
      const response = await fetchImpl(path, { headers: docHeaders, signal: abort.signal })
      if (response.ok) {
        const value = await response.json()
        if (!stopped) onProgress(value)
      }
    } catch { /* A missed progress update must not discard the actual result. */ }
    if (!stopped) timer = setTimeout(poll, pollMs)
  }
  function stop() {
    if (stopped) return
    stopped = true
    clearTimeout(timer)
    abort.abort()
    // Independent signal: the request being cancelled cannot cancel its cleanup.
    fetchImpl(path, { method: 'DELETE', headers: docHeaders }).catch(() => {})
  }
  signal?.addEventListener('abort', stop, { once: true })
  window.addEventListener('nadoc:document-reset', stop, { once: true })
  onProgress({ stage: 'Preparing geometry', percent: 0 })
  timer = setTimeout(poll, pollMs)
  try {
    return await run(id, abort.signal)
  } finally {
    stop()
    signal?.removeEventListener('abort', stop)
    window.removeEventListener('nadoc:document-reset', stop)
  }
}
