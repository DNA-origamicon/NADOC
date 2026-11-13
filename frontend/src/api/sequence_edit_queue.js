/** Serialize writes; replace only edits that have not reached the server. */
export function createSequenceEditQueue() {
  let running = false
  const pending = new Map()
  async function drain() {
    if (running) return
    running = true
    try {
      while (pending.size) {
        const [key, entry] = pending.entries().next().value
        pending.delete(key)
        try { entry.resolve(entry.current() ? await entry.run() : null) }
        catch (error) { entry.reject(error) }
      }
    } finally { running = false }
  }
  return (key, run, current = () => true) => new Promise((resolve, reject) => {
    pending.get(key)?.resolve(null)
    pending.set(key, { run, current, resolve, reject })
    void drain()
  })
}
