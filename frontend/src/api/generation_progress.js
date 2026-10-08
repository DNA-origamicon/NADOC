/** Poll actual backend stages; stop on success, failure, or document teardown. */
export async function withGenerationProgress(docHeaders, run, onProgress, { fetchImpl = fetch, pollMs = 350 } = {}) {
  if (!onProgress) return run(undefined)
  const id = crypto.randomUUID()
  let stopped = false, timer
  const abort = new AbortController()
  async function poll() {
    try {
      const response = await fetchImpl(`/api/design/generate-design/progress/${id}`, { headers: docHeaders, signal: abort.signal })
      if (response.ok) {
        const value = await response.json()
        if (!stopped) onProgress(value)
      }
    } catch { /* Progress availability must not fail construction. */ }
    if (!stopped) timer = setTimeout(poll, pollMs)
  }
  const stop = () => { stopped = true; clearTimeout(timer); abort.abort() }
  window.addEventListener('nadoc:document-reset', stop, { once: true })
  onProgress({ state: 'running', stage: 'Planning', detail: 'Compare scaffold budgets and paths', fraction: 0, steps: [] })
  timer = setTimeout(poll, pollMs)
  try {
    const result = await run(id)
    if (result && !stopped) onProgress({ state: 'complete', stage: 'Complete', detail: 'Geometry and construction history loaded', fraction: 1 })
    return result
  } finally {
    stop()
    window.removeEventListener('nadoc:document-reset', stop)
  }
}
