// Keep complete recovery serialization off the first visible undo/redo frame.
// Coalesce per document; pagehide flushes pending writes before navigation.
export function createDeferredRecovery({ delay = 200, target = globalThis.window } = {}) {
  const pending = new Map()
  const cancel = key => { clearTimeout(pending.get(key)?.timer); pending.delete(key) }
  const flush = () => {
    const writes = [...pending.values()]
    for (const key of pending.keys()) cancel(key)
    for (const { write } of writes) write()
  }
  target?.addEventListener('pagehide', flush)
  return {
    cancel, flush,
    schedule(key, write) {
      cancel(key)
      const task = { write, timer: null }
      pending.set(key, task)
      const schedule = () => {
        if (pending.get(key) !== task) return
        task.timer = setTimeout(() => { pending.delete(key); write() }, delay)
      }
      if (globalThis.requestAnimationFrame) requestAnimationFrame(() => requestAnimationFrame(schedule))
      else schedule()
    },
    dispose() { flush(); target?.removeEventListener('pagehide', flush) },
  }
}
