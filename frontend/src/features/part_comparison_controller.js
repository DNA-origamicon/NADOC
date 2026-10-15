import { repairIssues, repairJobView, sameRepairContext } from './part_repair_model.js'
import { validatePartComparisonEnvelope } from './part_comparison_model.js'

/** One private read/view lifetime; the existing repair controller owns the job. */
export function createPartComparisonController({ api, repair, events = globalThis.window,
  now = () => performance.now() }) {
  let state = { open: false, busy: false, projection: null, binding: null, error: null, issues: [] }
  let epoch = 0, disposed = false, abort = null, expiry = null
  const listeners = new Set()
  const snapshot = () => ({ ...state })
  const emit = () => { if (!disposed) for (const listener of listeners) listener(snapshot()) }
  function bindingFor(current) {
    const job = current?.job
    if (!job || current.busy || current.publication || current.refreshNeeded || current.requiresReview
        || !repairJobView(job, current.context, current.draft).ready) return null
    return { context: { ...current.context }, jobId: job.id, draftId: job.draftId, generation: job.generation }
  }
  const matches = binding => {
    const next = bindingFor(repair.getState())
    return !!next && sameRepairContext(binding.context, next.context) && binding.jobId === next.jobId
      && binding.draftId === next.draftId && binding.generation === next.generation
  }
  function invalidate({ close = false, error = null } = {}) {
    epoch++; abort?.abort(); abort = null; clearTimeout(expiry); expiry = null
    state = { open: close ? false : state.open, busy: false, projection: null, binding: null, error,
      issues: error ? repairIssues(error) : [] }
    emit()
  }
  function refresh() {
    if (disposed || !state.binding || matches(state.binding)) return
    const contextChanged = !sameRepairContext(state.binding.context, repair.getState()?.context)
    invalidate({ close: contextChanged, error: contextChanged ? null : new Error('The evaluated proposal changed. Request a current comparison.') })
  }
  const unsubscribe = repair.subscribe(refresh)
  const reset = () => { if (!disposed) invalidate({ close: true }) }
  events?.addEventListener('nadoc:document-reset', reset)

  return {
    getState: snapshot,
    subscribe(listener) { listeners.add(listener); listener(snapshot()); return () => listeners.delete(listener) },
    async open() {
      if (disposed) return null
      refresh()
      if (state.busy || state.projection) return state.projection
      const binding = bindingFor(repair.getState())
      if (!binding) {
        state = { ...state, open: true, error: new Error('Evaluate the current saved proposal before requesting comparison') }; emit(); return null
      }
      const token = ++epoch, started = now(), request = new AbortController()
      abort = request
      const current = () => !disposed && token === epoch && matches(binding)
      state = { open: true, busy: true, projection: null, binding, error: null, issues: [] }; emit()
      try {
        const value = await api.compare(binding.jobId, { projection_version: 1,
          expected_design_id: binding.context.designId, expected_revision: binding.context.revision,
          expected_draft_id: binding.draftId, expected_generation: binding.generation },
        { context: binding.context, signal: request.signal })
        if (!current()) return null
        const projection = validatePartComparisonEnvelope(value, binding)
        const remaining = projection.expires_in_seconds * 1000 - Math.max(0, now() - started)
        if (remaining <= 0) throw new Error('The comparison expired before it could be displayed')
        // Conservative: server's remaining interval is charged from request start.
        // The completed repair has its own lifecycle; this timer owns only display.
        expiry = setTimeout(() => {
          if (!disposed && token === epoch) invalidate({ error: new Error('The comparison expired. Request a current comparison.') })
        }, remaining)
        state = { ...state, busy: false, projection }; emit()
        return current() ? projection : null
      } catch (error) {
        if (current()) {
          state = { ...state, busy: false, projection: null, error, issues: repairIssues(error) }; emit()
        }
        return null
      } finally {
        if (abort === request) abort = null
        // A source change without an emitted subscription still invalidates data.
        if (!disposed && token === epoch && !matches(binding)) refresh()
      }
    },
    close() { if (!disposed) invalidate({ close: true }) },
    dispose() {
      if (disposed) return
      disposed = true; epoch++; abort?.abort(); abort = null; clearTimeout(expiry); expiry = null
      state = { ...state, open: false, busy: false, projection: null, binding: null }
      unsubscribe?.(); listeners.clear(); events?.removeEventListener('nadoc:document-reset', reset)
    },
  }
}
