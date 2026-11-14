import { flexRangeKey } from './md_flex_range.js'
const labels = {
  starting: 'Starting flexibility analysis',
  rmsf_setup: 'Loading topology and mapping bases',
  rmsf: 'Measuring flexibility',
  tail_preview: 'Preliminary map · last chunk of frames',
  backfill: 'Preliminary map · processing remaining frames',
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
export function withFlexProgress(api, id, kind, request, onProgress, onPartial, frameRange) {
  if ((!onProgress && !onPartial) || !api.getMdFlexProgress) return request()
  return (async () => {
    const abort = new AbortController()
    let timer = null
    let finished = false
    let revision = 0
    let painting = Promise.resolve()
    onProgress?.({ phase: 'starting', done: 0, total: 1 })
    const poll = async () => {
      try {
        const state = await api.getMdFlexProgress(id, kind, abort.signal, revision)
        if (!finished && state?.active && (frameRange === undefined ||
            (state.frame_range !== undefined && flexRangeKey(state.frame_range) === flexRangeKey(frameRange)))) {
          onProgress?.(state)
          if (state.partial && state.revision > revision) {
            revision = state.revision
            painting = Promise.resolve(onPartial?.(state.partial, state.representations))
            await painting
          }
        }
      } catch { /* the analysis request reports failures */ }
      if (!finished) timer = setTimeout(poll, 400)
    }
    timer = setTimeout(poll, 200)
    try {
      const result = await request()
      finished = true
      await painting
      return result
    } finally {
      finished = true
      clearTimeout(timer)
      abort.abort()
    }
  })()
}

/** Drawing a provisional representation never completes the ensemble calculation. */
export function flexDisplayProgress(state, response) {
  if (!response?.preliminary) return state
  const coverage = response.coverage || {}
  return { ...state, complete: false, preliminary: true,
    phase: coverage.phase || 'backfill', done: coverage.processed_frames ?? response.n_frames,
    total: coverage.total_frames ?? 0 }
}
