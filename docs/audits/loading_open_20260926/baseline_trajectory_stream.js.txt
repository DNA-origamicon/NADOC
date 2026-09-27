/** Bounded look-ahead over exact trajectory pages. No missing frame is substituted.
 * Serializes page requests, deduplicates scrubs, and discards obsolete responses.
 */
export function initTrajectoryStream({ total, pageSize = 8, firstPageSize = pageSize, load, apply, live }) {
  const ready = new Set(), pending = new Map()
  let tail = Promise.resolve()
  const pageAt = i => i < firstPageSize ? 0 : 1 + Math.floor((i - firstPageSize) / pageSize)
  const pageStart = page => page === 0 ? 0 : firstPageSize + (page - 1) * pageSize
  function ensure(index) {
    if (!live()) return Promise.resolve(false)
    const page = pageAt(Math.max(0, Math.min(total - 1, index)))
    if (ready.has(page)) return Promise.resolve(true)
    if (pending.has(page)) return pending.get(page)
    const start = pageStart(page), end = Math.min(total - 1, pageStart(page + 1) - 1)
    const promise = tail.catch(() => {}).then(async () => {
      if (!live()) return false
      const result = await load(start, end)
      if (!live()) return false
      await apply(result, start, end)
      if (!live()) return false
      ready.add(page)
      return true
    }).finally(() => pending.delete(page))
    pending.set(page, promise)
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
  return { ensure, prefetch, fill, forget: index => ready.delete(pageAt(index)) }
}
