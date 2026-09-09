/** Coordinate downloads shared by background authoring and foreground playback.
 * No display/controller state is changed here. Failed requests remain retryable.
 */
export function initTrajectoryDownloads(fetchTrajectory) {
  const entries = new Map()
  const jobTails = new Map()
  let retained = new Set()
  const key = (jobId, { align = true, scope = 'lineage', stride } = {}) =>
    JSON.stringify([jobId, align, scope, stride ?? null])

  function get(jobId, spec = {}, { signal, onProgress } = {}) {
    if (signal?.aborted) return Promise.reject(new DOMException('cancelled', 'AbortError'))
    const id = key(jobId, spec)
    let entry = entries.get(id)
    if (!entry) {
      const abort = new AbortController()
      entry = { abort, listeners: new Set(), promise: null, done: false }
      entries.set(id, entry)
      if (onProgress) entry.listeners.add(onProgress)
      // NAMD analysis has one worker slot per job/kind. Two resolutions of the
      // same trajectory must not start competing extraction requests.
      const begin = () => {
        if (abort.signal.aborted) throw new DOMException('cancelled', 'AbortError')
        return fetchTrajectory(jobId, {
          ...spec, signal: abort.signal,
          onProgress: p => { for (const cb of entry.listeners) cb(p) },
        })
      }
      const previous = jobTails.get(jobId)
      entry.promise = (previous ? previous.catch(() => {}).then(begin) : Promise.resolve(begin())).then(result => {
        entry.done = true
        if (!result?.ready || !result.frames?.length) {
          if (entries.get(id) === entry) entries.delete(id)
        }
        return result
      }).catch(error => {
        if (entries.get(id) === entry) entries.delete(id)
        throw error
      })
      jobTails.set(jobId, entry.promise)
      const complete = () => { if (jobTails.get(jobId) === entry.promise) jobTails.delete(jobId) }
      entry.promise.then(complete, complete)
    }
    if (onProgress) entry.listeners.add(onProgress)
    const cancel = () => {
      entry.abort.abort()
      if (entries.get(id) === entry) entries.delete(id)
    }
    if (signal?.aborted) cancel()
    signal?.addEventListener('abort', cancel, { once: true })
    return entry.promise.finally(() => {
      entry.listeners.delete(onProgress)
      signal?.removeEventListener('abort', cancel)
    })
  }

  function retain(requests) {
    const wanted = new Set(requests.map(({ jobId, ...spec }) => key(jobId, spec)))
    retained = wanted
    for (const [id, entry] of entries) {
      if (wanted.has(id)) continue
      entry.abort.abort()
      entries.delete(id)
    }
  }
  function seed(jobId, spec, result) {
    const id = key(jobId, spec)
    if (!entries.has(id)) entries.set(id, {
      abort: new AbortController(), listeners: new Set(), done: true,
      promise: Promise.resolve(result),
    })
  }
  function cancelPending() {
    for (const [id, entry] of entries) {
      if (entry.done) continue
      entry.abort.abort()
      entries.delete(id)
    }
  }
  function consumed(jobId, spec) {
    const id = key(jobId, spec)
    if (!retained.has(id)) entries.delete(id)
  }
  return { get, retain, consumed, seed, cancelPending, clear: () => retain([]) }
}
