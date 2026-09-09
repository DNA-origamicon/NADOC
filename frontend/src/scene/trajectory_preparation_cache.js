/** Prepare heavy trajectory frames off-screen using the existing display pipeline.
 * The session has no scene/renderers; only completed caches are adopted by playback.
 */
export function initTrajectoryPreparationCache({ context, download, createSession }) {
  const entries = new Map()
  let tail = Promise.resolve()
  const key = (jobId, spec) => JSON.stringify([jobId, spec.scope, spec.stride ?? null, context()])

  function prepare(jobId, spec, { onProgress, planPrebuild, schedule } = {}) {
    const id = key(jobId, spec)
    let entry = entries.get(id)
    if (!entry) {
      entry = { jobId, spec, listeners: new Set(), state: 'loading', progress: null, session: null, cancelled: false }
      entries.set(id, entry)
      const report = progress => {
        entry.progress = progress
        for (const listener of entry.listeners) listener(progress)
      }
      if (onProgress) entry.listeners.add(onProgress)
      report({ phase: 'queued', done: 0, total: 0 })
      const settings = context()
      const cancelled = new Promise((_, reject) => { entry.rejectCancel = reject })
      const run = async () => {
        if (entry.cancelled) throw new DOMException('cancelled', 'AbortError')
        report({ phase: 'load', done: 0, total: 0 })
        const data = await download(jobId, spec, { onProgress: report })
        if (entry.cancelled) throw new DOMException('cancelled', 'AbortError')
        report({ phase: 'load', done: data?.n_frames || 0, total: data?.n_frames || 0 })
        entry.session = createSession(data, settings)
        const loaded = await entry.session.loadTrajectory(jobId, true, spec.scope, spec.stride)
        if (!loaded?.ok) throw new Error(loaded?.reason || 'Trajectory unavailable')
        report({ phase: 'frames', done: 0, total: 0, trajectoryFrames: data.n_frames })
        const plan = await planPrebuild?.(entry.session)
        if (entry.cancelled) throw new DOMException('cancelled', 'AbortError')
        const result = await entry.session.prebuildHeavy(
          (done, total, detail) => report({ ...detail, phase: 'frames', done, total }),
          { budgetBytes: plan?.budgetBytes ?? null },
        )
        if (entry.cancelled) throw new DOMException('cancelled', 'AbortError')
        if (!result?.ok) throw new Error('Frame preparation was interrupted')
        entry.snapshot = entry.session.trajectoryPreparationState()
        entry.state = 'ready'
        report({ phase: 'ready', done: result.frames ?? result.n ?? 0,
          total: result.frames ?? result.n ?? 0, capped: !!result.capped,
          trajectoryFrames: data.n_frames })
        return { n_frames: data.n_frames, ...result }
      }
      const work = (schedule ? schedule(run) : tail.catch(() => {}).then(run)).catch(error => {
        entry.state = 'error'
        report({ phase: error?.name === 'AbortError' ? 'cancelled' : 'error', done: 0, total: 0 })
        if (entries.get(id) === entry) entries.delete(id)
        throw error
      })
      entry.promise = Promise.race([work, cancelled])
      if (!schedule) tail = work
      work.catch(() => {})
    } else if (onProgress) {
      entry.listeners.add(onProgress)
      if (entry.progress) onProgress(entry.progress)
    }
    return entry.promise.finally(() => entry.listeners.delete(onProgress))
  }

  function retain(requests) {
    const wanted = new Set(requests.map(({ jobId, ...spec }) => key(jobId, spec)))
    for (const [id, entry] of entries) {
      if (wanted.has(id)) continue
      entry.cancelled = true
      entry.progress = { phase: 'cancelled', done: 0, total: 0 }
      for (const listener of entry.listeners) listener(entry.progress)
      entry.rejectCancel?.(new DOMException('cancelled', 'AbortError'))
      entry.session?.cancelPendingLoad?.()
      entry.session?.setPlaying?.(false)
      entries.delete(id)
    }
  }
  function cancel() {
    for (const [id, entry] of entries) {
      if (entry.state === 'ready') continue
      entry.cancelled = true
      entry.progress = { phase: 'cancelled', done: 0, total: 0 }
      for (const listener of entry.listeners) listener(entry.progress)
      entry.rejectCancel?.(new DOMException('cancelled', 'AbortError'))
      entry.session?.cancelPendingLoad?.()
      entry.session?.setPlaying?.(false)
      entries.delete(id)
    }
  }
  return { prepare, retain, cancel, snapshot: (jobId, spec) => entries.get(key(jobId, spec))?.snapshot }
}
