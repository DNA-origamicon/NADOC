/** Bounded look-ahead over exact trajectory pages. No missing frame is substituted.
 * Serializes page requests, deduplicates scrubs, and discards obsolete responses.
 */
export function initTrajectoryStream({ total, pageSize = 8, firstPageSize = pageSize, load, apply, live }) {
  const ready = new Set(), pending = new Map()
  let tail = Promise.resolve()
  const pageAt = i => i < firstPageSize ? 0 : 1 + Math.floor((i - firstPageSize) / pageSize)
  const pageStart = page => page === 0 ? 0 : firstPageSize + (page - 1) * pageSize
  function cancelPendingSeeks(exceptPage = -1) {
    for (const [page, task] of pending) {
      if (page !== exceptPage && task.latest && !task.started) task.cancelled = true
    }
  }
  function ensure(index, latest = false) {
    if (!live()) return Promise.resolve(false)
    const page = pageAt(Math.max(0, Math.min(total - 1, index)))
    if (latest) cancelPendingSeeks(page)
    if (ready.has(page)) return Promise.resolve(true)
    const existing = pending.get(page)
    if (existing && !existing.cancelled) {
      // An explicit preparation/playback consumer must still receive its frame,
      // even if an interactive scrub shares the same pending page.
      if (!latest) existing.latest = false
      return existing.promise
    }
    const start = pageStart(page), end = Math.min(total - 1, pageStart(page + 1) - 1)
    const task = { latest, started: false, cancelled: false }
    const promise = tail.catch(() => {}).then(async () => {
      if (!live() || task.cancelled) return false
      task.started = true
      const result = await load(start, end)
      if (!live()) return false
      await apply(result, start, end)
      if (!live()) return false
      ready.add(page)
      return true
    }).finally(() => { if (pending.get(page) === task) pending.delete(page) })
    task.promise = promise
    pending.set(page, task)
    tail = promise
    return promise
  }
  function prefetch(index) {
    const next = pageStart(pageAt(index) + 1)
    if (next < total && live()) ensure(next).catch(() => {}) // a later seek retries/report errors
  }
  // Queue only one background page at a time. A foreground seek arriving during
  // its read is queued ahead of the next background page.
  let filling = null
  function fill({ canContinue = () => true, onProgress = () => {} } = {}) {
    if (filling) return filling
    filling = (async () => {
      for (let page = 0; pageStart(page) < total && live(); page++) {
        if (!ready.has(page) && !canContinue()) break
        if (!await ensure(pageStart(page))) break
        onProgress()
        await new Promise(resolve => setTimeout(resolve, 0))
      }
    })().finally(() => { filling = null })
    return filling
  }
  return { ensure: index => ensure(index), seek: index => ensure(index, true),
    cancelPendingSeeks, prefetch, fill, forget: index => ready.delete(pageAt(index)) }
}
