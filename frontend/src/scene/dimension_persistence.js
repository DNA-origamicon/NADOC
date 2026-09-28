/** Shared saved records. Requests stay bound to the document that initiated them. */
export function initDimensionPersistence({ store, transport, onRecords, onError = () => {} }) {
  if (!transport) return { change() {}, reload() {}, dispose() {} }
  let pending = 0, stopped = false, loading = false, sending = false, reported = false
  const jobs = []
  let identity = '', signature = ''
  function context() {
    const s = store.getState()
    const kind = s.assemblyActive ? 'assembly' : 'design'
    const document = s.assemblyActive ? s.currentAssembly : s.currentDesign
    return { kind, id: document?.id, document }
  }
  function receive() {
    const ctx = context(), next = `${ctx.kind}:${ctx.id ?? ''}`
    const changed = next !== identity
    if (changed) { identity = next; signature = '' }
    if (pending && !changed) return
    const records = ctx.document?.dimensions ?? []
    const value = JSON.stringify(records)
    if (value !== signature) { signature = value; onRecords(records) }
  }
  async function drain() {
    if (sending || stopped) return
    sending = true
    try {
      while (jobs.length && !stopped) {
        const job = jobs[0]
        try {
          await transport.save(job.ctx.kind, job.ctx.id, job.upsert, job.deleted, job.request)
          jobs.shift(); pending = jobs.length; reported = false
        } catch (error) {
          if (!reported) onError(error)
          reported = true
          break // Keep the operation and its visible record; next timer retries.
        }
      }
    } finally { sending = false; if (!pending) receive() }
  }
  async function refresh() {
    if (stopped || loading) return
    if (pending) { await drain(); return }
    const ctx = context()
    if (!ctx.id) return
    loading = true
    try { await transport.load(ctx.kind, ctx.id); receive() }
    catch (error) { onError(error) }
    finally { loading = false }
  }
  const unsubscribe = store.subscribe(receive)
  receive()
  const timer = setInterval(refresh, 1000)
  void refresh()
  return {
    change(upsert = [], deleted = []) {
      const ctx = context()
      if (!ctx.id) return
      const request = transport.capture?.() ?? {}
      jobs.push({ ctx, upsert: structuredClone(upsert), deleted: [...deleted], request })
      pending = jobs.length
      return drain()
    },
    reload() { signature = ''; receive() },
    dispose() { stopped = true; clearInterval(timer); unsubscribe?.() },
  }
}
