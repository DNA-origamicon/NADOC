const aborted = () => new DOMException('Read superseded or cancelled', 'AbortError')

/** Client transport coordination, independent of diagnostic operation timing.
 * Abandoning a subscriber never releases an in-flight transport before it drains.
 * Foreground calls retain their existing mutual concurrency; only passive work waits.
 */
export function createPassiveReadScheduler({ maxPending = 4, maxSubscribers = 16 } = {}) {
  const pending = new Map(), foreground = []
  let passive = null, activeForeground = 0, scheduled = false, generation = 0
  const schedule = () => {
    if (!scheduled) { scheduled = true; Promise.resolve().then(() => Promise.resolve().then(pump)) }
  }
  function settle(entry, error, value) {
    for (const waiter of entry.waiters) {
      waiter.signal?.removeEventListener('abort', waiter.cancel)
      if (!waiter.current() || (entry.passive && entry.generation !== generation)) waiter.reject(aborted())
      else if (error) waiter.reject(error)
      else waiter.resolve(value)
    }
    entry.waiters.clear()
  }
  function start(entry) {
    if (entry.passive) passive = entry
    else activeForeground++
    let work
    try { work = Promise.resolve(entry.task()) } catch (error) { work = Promise.reject(error) }
    work.then(value => settle(entry, null, value), error => settle(entry, error))
      .finally(() => {
        if (entry.passive) passive = null
        else activeForeground--
        schedule()
      })
  }
  function pump() {
    scheduled = false
    if (passive) return
    while (foreground.length) {
      const entry = foreground.shift()
      if (entry.waiters.size) start(entry)
    }
    if (activeForeground) return
    for (const [key, entry] of pending) {
      pending.delete(key)
      for (const waiter of [...entry.waiters]) if (!waiter.current()) waiter.cancel()
      if (entry.waiters.size) { start(entry); return }
    }
  }
  return {
    run(key, task, { passive: isPassive = false, signal, current = () => true } = {}) {
      if (signal?.aborted || !current()) return Promise.reject(aborted())
      let entry = isPassive ? pending.get(key) : null
      if ((!entry && (isPassive ? pending.size >= maxPending : foreground.length >= 16))
          || (entry && entry.waiters.size >= maxSubscribers)) return Promise.reject(new Error('Passive read coordination queue is full'))
      if (!entry) entry = { key, task, passive: isPassive, generation, waiters: new Set() }
      const result = new Promise((resolve, reject) => {
        const waiter = { resolve, reject, signal, current, cancel: null }
        waiter.cancel = () => {
          signal?.removeEventListener('abort', waiter.cancel)
          entry.waiters.delete(waiter); reject(aborted())
          if (!entry.waiters.size && pending.get(key) === entry) pending.delete(key)
        }
        entry.waiters.add(waiter)
        signal?.addEventListener('abort', waiter.cancel, { once: true })
      })
      if (isPassive) { pending.set(key, entry); schedule() }
      else if (passive) foreground.push(entry)
      else start(entry)
      return result
    },
    reset() {
      generation++
      for (const entry of pending.values()) settle(entry, aborted())
      pending.clear()
      if (passive) settle(passive, aborted())
    },
  }
}

export const passiveReadScheduler = createPassiveReadScheduler()
const reset = () => passiveReadScheduler.reset()
globalThis.window?.addEventListener('nadoc:document-reset', reset)
if (import.meta.hot) import.meta.hot.dispose(() => {
  reset(); globalThis.window?.removeEventListener('nadoc:document-reset', reset)
})

export const isPassiveRead = (method, path) => method === 'GET'
  && /^\/(?:design\/(?:view-volumes|dimensions|readiness)|jobs\/active)(?:\?|$)/.test(path)
