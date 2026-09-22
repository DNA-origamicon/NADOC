const labels = {
  starting: 'Starting flexibility analysis',
  rmsf_setup: 'Loading topology and mapping bases',
  rmsf: 'Measuring flexibility',
  atomistic_setup: 'Mapping simulation atoms',
  atomistic_average: 'Averaging atom positions',
  atomistic_topology: 'Preparing atom bonds',
  surface: 'Building molecular surface',
  transfer: 'Receiving representation',
  display: 'Drawing representation',
}

/** Percentages describe completed work within the named stage, not guessed time. */
export function flexProgressView(progress = {}) {
  const total = Number(progress.total) || 0
  const done = Math.max(0, Number(progress.done) || 0)
  const percent = total > 0 ? Math.min(100, Math.floor(done / total * 100)) : 0
  const counts = total > 1 ? ` · ${done}/${total}` : ''
  const seconds = Math.floor(progress.elapsed_seconds || 0)
  const elapsed = seconds > 0 ? ` · ${seconds}s elapsed` : ''
  return { percent, text: `${labels[progress.phase] || 'Loading flexibility map'} · ${percent}%${counts}${elapsed}` }
}

/** Observe a worker only for the lifetime of its request; polling errors are advisory. */
export function withFlexProgress(api, id, kind, request, onProgress) {
  if (!onProgress || !api.getMdFlexProgress) return request()
  return (async () => {
    const abort = new AbortController()
    let timer = null
    let finished = false
    onProgress({ phase: 'starting', done: 0, total: 1 })
    const poll = async () => {
      try {
        const state = await api.getMdFlexProgress(id, kind, abort.signal)
        if (!finished && state?.active) onProgress(state)
      } catch { /* the analysis request reports failures */ }
      if (!finished) timer = setTimeout(poll, 400)
    }
    timer = setTimeout(poll, 200)
    try {
      return await request()
    } finally {
      finished = true
      clearTimeout(timer)
      abort.abort()
    }
  })()
}
