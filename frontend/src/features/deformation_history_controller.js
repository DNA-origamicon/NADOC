import { cloneRepairInput, sameRepairContext } from './part_repair_model.js'
import { DeformationPreviewRequestError, previewPublicationReceipt } from '../api/deformation_preview_endpoints.js'

const CONTEXT = ['docId', 'designId', 'revision', 'loadoutId', 'editable', 'cursor', 'subCursor']
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const refused = error => [403, 404, 408, 409, 410, 413, 422, 429].includes(error?.status)
const error = (message, status = 409) => new DeformationPreviewRequestError(status, message)
const empty = () => ({ mode: 'edit', awaitingParameters: false, open: false, busy: null, featureId: null, deformationId: null,
  draft: {}, projection: null, controls: null, error: null, expired: false,
  committed: null, refreshNeeded: false, publicationUnknown: false })
const contextCopy = context => Object.fromEntries(CONTEXT.map(key => [key, context?.[key]]))

/** Owns one private editor. Only applyPublished may adopt a canonical response. */
export function createDeformationHistoryController({ api, getContext, subscribeContext = () => () => {},
  validateDisplay, applyPublished, events = globalThis.window, uuid = () => crypto.randomUUID(), now = () => performance.now() }) {
  if (typeof validateDisplay !== 'function' || typeof applyPublished !== 'function') {
    throw new Error('Preview display validation and publication adoption are required')
  }
  let state = empty(), binding = null, epoch = 0, disposed = false, adopting = false, timer = null
  let active = null, pending = null, applyTask = null, publicationTask = null, applying = false
  let draftVersion = 0, evaluatedVersion = 0, pendingPublication = null
  const requests = new Set(), listeners = new Set()
  const snapshot = () => ({ ...state, draft: cloneRepairInput(state.draft),
    committed: state.committed ? { ...state.committed } : null,
    context: binding ? { ...binding.context } : null })
  const emit = () => { if (!disposed) for (const listener of listeners) listener(snapshot()) }
  const current = b => !disposed && binding === b && b.epoch === epoch && sameRepairContext(b.context, getContext())
  const options = (b, abort) => ({ context: { ...b.context }, ...(abort ? { signal: abort.signal } : {}) })
  const body = b => ({ ...b.origin, ...(b.lease ? { lease_id: b.lease } : {}) })
  const stopTimer = () => { clearTimeout(timer); timer = null }
  const abortRequests = () => { for (const request of requests) request.abort(); requests.clear() }
  function cleanup(b, lease = b?.lease) {
    if (!b) return
    try { Promise.resolve(api.cancel({ ...b.origin, ...(lease ? { lease_id: lease } : {}) }, options(b))).catch(() => {}) }
    catch { /* Best-effort cleanup never acquires publication authority. */ }
  }
  function discardPending() { pending?.resolve(null); pending = null }
  function invalidate() {
    const old = binding
    epoch++; stopTimer(); abortRequests(); discardPending()
    binding = null; active = null; applying = false; applyTask = null; publicationTask = null; pendingPublication = null
    state = empty(); cleanup(old); emit()
  }
  function refreshContext() {
    if (!disposed && !adopting && binding && !sameRepairContext(binding.context, getContext())) invalidate()
  }
  const unsubscribe = subscribeContext(refreshContext)
  const reset = () => { if (!adopting) invalidate() }
  events?.addEventListener('nadoc:document-reset', reset)

  function expire(b) {
    if (!current(b) || state.expired || state.committed) return
    stopTimer(); abortRequests(); discardPending()
    state = { ...state, expired: true, projection: null, busy: null,
      error: error('The preview expired. Reopen this feature to continue') }
    // An in-flight Apply may have published despite a lost/aborted response.
    if (pendingPublication) state.publicationUnknown = true
    cleanup(b); emit()
  }
  function leaseDeadline(b, response, started) {
    const seconds = response.remaining_seconds
    if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0 || seconds > 60) {
      throw error('The preview lease response is invalid', 422)
    }
    b.deadline = Math.min(b.deadline, started + seconds * 1000)
    stopTimer()
    if (b.deadline <= now()) { expire(b); throw error('The preview expired. Reopen this feature to continue') }
    timer = setTimeout(() => expire(b), b.deadline - now())
  }
  function envelope(b, response, sequence, { opening = false } = {}) {
    if (!response || Object.entries(b.origin).some(([key, value]) => response[key] !== value)
        || response.doc_id !== (b.context.docId ?? '__default__')
        || !UUID.test(response.lease_id ?? '') || (!opening && response.lease_id !== b.lease)
        || typeof response.deformation_id !== 'string' || !response.deformation_id || response.deformation_id.length > 256
        || (!opening && response.deformation_id !== b.deformationId)
        || response.request_sequence !== sequence) throw error('The preview response belongs to another feature or revision')
  }
  function available() {
    refreshContext()
    if (!binding || !state.open || disposed || state.expired || !binding.lease || state.committed || state.publicationUnknown) return false
    if (binding.deadline <= now()) { expire(binding); return false }
    return true
  }
  function setError(b, failure) { if (current(b)) { state = { ...state, error: failure }; emit() } }
  function nextSequence(b) {
    if (b.sequence >= 2 ** 31 - 1) throw error('Reopen the feature to continue editing')
    return ++b.sequence
  }

  async function open(featureId, creation = null) {
    if (disposed) return null
    invalidate()
    const context = contextCopy(getContext())
    if (!context.designId || !Number.isSafeInteger(context.revision) || context.revision < 0
        || context.editable !== true || context.cursor !== -1 || context.subCursor != null
        || !Object.hasOwn(getContext() ?? {}, 'docId') || !(context.docId === null || typeof context.docId === 'string')
        || typeof featureId !== 'string' || !featureId || featureId.length > 256) {
      state = { ...state, error: error('Choose a feature in the current editable part revision', 422) }; emit(); return null
    }
    const nonce = uuid()
    if (!UUID.test(nonce)) { state = { ...state, error: error('A fresh preview identity is required', 422) }; emit(); return null }
    const b = { context, epoch, origin: { preview_id: nonce, expected_design_id: context.designId,
      expected_revision: context.revision, feature_id: featureId }, lease: null, deformationId: null, sequence: 0, deadline: Infinity }
    b.mode = creation ? 'create' : 'edit'
    binding = b; draftVersion = 0; evaluatedVersion = creation ? -1 : 0
    state = { ...empty(), mode: b.mode, awaitingParameters: !!creation, open: true, featureId, busy: 'prepare' }; emit()
    const abort = new AbortController(), started = now(); requests.add(abort)
    try {
      const response = creation
        ? await api.prepareCreation({ ...body(b), mode: 'create', ...creation }, options(b, abort))
        : await api.prepare(body(b), options(b, abort))
      if (!current(b)) {
        try { envelope(b, response, 0, { opening: true }); cleanup(b, response.lease_id) } catch { /* original nonce cancellation remains authoritative */ }
        return null
      }
      envelope(b, response, 0, { opening: true })
      displayMode(b, response, true)
      validateDisplay(response, { prepare: true })
      b.lease = response.lease_id; b.deformationId = response.deformation_id
      leaseDeadline(b, response, started)
      state = { ...state, deformationId: b.deformationId, projection: response, controls: response.control_context, error: null }
      emit(); return response
    } catch (failure) { setError(b, failure); return null }
    finally { requests.delete(abort); if (current(b)) { state = { ...state, busy: null }; emit() } }
  }

  function openCreation({ type, targets, clusterIds } = {}) {
    try {
      const creation = cloneRepairInput({ type, targets, cluster_ids: clusterIds })
      if (!['bend', 'twist'].includes(type) || !Array.isArray(clusterIds)
          || !(targets === null || (Array.isArray(targets) && targets.length > 0))) throw error('Choose an explicit deformation scope', 422)
      const featureId = uuid()
      if (!UUID.test(featureId)) throw error('A fresh feature identity is required', 422)
      return open(featureId, creation)
    } catch (failure) { state = { ...state, error: failure }; emit(); return Promise.resolve(null) }
  }
  function displayMode(b, response, preparing) {
    if (b.mode === 'create') {
      if (response.mode !== 'create' || response.awaiting_parameters !== preparing) throw error('Invalid creation preview stage', 422)
    } else if (Object.hasOwn(response, 'mode') || Object.hasOwn(response, 'awaiting_parameters')) {
      throw error('Creation preview cannot replace a history edit', 422)
    }
  }

  async function evaluate(entry) {
    const b = entry.binding, abort = new AbortController(), started = now()
    requests.add(abort)
    state = { ...state, busy: applying ? 'apply' : 'evaluate' }; emit()
    try {
      const response = await api.evaluate({ ...body(b), request_sequence: nextSequence(b),
        params: entry.draft, include_geometry: entry.includeGeometry }, options(b, abort))
      if (!current(b) || state.expired || entry.version !== draftVersion) return null
      envelope(b, response, b.sequence)
      displayMode(b, response, false)
      validateDisplay(response, { prepare: false })
      leaseDeadline(b, response, started)
      evaluatedVersion = entry.version
      state = { ...state, awaitingParameters: false, projection: response, error: null }; emit(); return response
    } catch (failure) { if (entry.version === draftVersion) setError(b, failure); return null }
    finally { requests.delete(abort) }
  }
  function pump() {
    if (active || !pending || !available()) return
    const entry = pending; pending = null
    const task = evaluate(entry)
    active = task
    void task.then(entry.resolve).finally(() => {
      if (active !== task) return
      active = null
      if (pending && available()) pump()
      else if (current(entry.binding) && !applying) { state = { ...state, busy: null }; emit() }
    })
  }
  function update(patch, { includeGeometry = true } = {}) {
    if (!available() || applying || publicationTask) return Promise.resolve(null)
    try {
      const copy = cloneRepairInput(patch)
      if (!copy || Array.isArray(copy) || typeof copy !== 'object' || typeof includeGeometry !== 'boolean') {
        throw error('Preview changes must be an input object', 422)
      }
      state = { ...state, draft: cloneRepairInput({ ...state.draft, ...copy }), error: null }
      draftVersion++; discardPending()
      const promise = new Promise(resolve => { pending = { binding, version: draftVersion,
        draft: cloneRepairInput(state.draft), includeGeometry, resolve } })
      emit(); pump(); return promise
    } catch (failure) { setError(binding, failure); return Promise.resolve(null) }
  }

  function acceptPublication(b, response, sequence) {
    // Apply/Cancel retain a small receipt. Origin and operation identity come
    // only from this editor's checked binding; supplied conflicts still fail.
    const complete = { ...b.origin, deformation_id: b.deformationId, ...response }
    envelope(b, complete, sequence)
    const receipt = previewPublicationReceipt(complete, b.context)
    if (state.committed) {
      previewPublicationReceipt(receipt, b.context, state.committed)
      return state.committed
    }
    pendingPublication = null; stopTimer()
    state = { ...state, committed: receipt, publicationUnknown: false, refreshNeeded: true, error: null }
    emit(); return receipt
  }
  async function refreshPublication(b, abort) {
    const receipt = state.committed
    if (!receipt || !state.refreshNeeded) return null
    const result = await api.refreshCommitted({ ...receipt }, options(b, abort))
    if (!current(b) || state.committed !== receipt) return null
    adopting = true
    let adopted, adoptedContext
    try {
      // Canonical adoption must happen synchronously under this final local
      // check. Its returned promise may finish rendering, never a deferred write.
      adopted = applyPublished(result, { ...b.context }, { ...receipt })
      if (adopted === false) throw error('The publication is no longer current')
      adoptedContext = contextCopy(getContext())
    } finally { adopting = false }
    await adopted
    if (disposed || binding !== b || b.epoch !== epoch || !sameRepairContext(adoptedContext, getContext())) return null
    state = { ...state, open: false, projection: null, controls: null, refreshNeeded: false, error: null }
    emit(); return result
  }
  async function doApply() {
    if (!available() || publicationTask) return null
    const b = binding
    applying = true; state = { ...state, busy: 'apply' }; emit()
    const abort = new AbortController(); requests.add(abort)
    try {
      while (current(b) && (active || pending)) {
        if (!active) pump()
        if (!active) break
        await active
        // pump's completion handler owns releasing the active slot.
        await Promise.resolve()
      }
      if (!current(b) || !available() || evaluatedVersion !== draftVersion) return null
      const sequence = nextSequence(b)
      pendingPublication = { binding: b, sequence }
      let response
      try {
        response = await api.apply({ ...body(b), request_sequence: sequence, params: cloneRepairInput(state.draft) }, options(b, abort))
      } catch (failure) {
        if (current(b)) {
          if (refused(failure)) pendingPublication = null
          state = { ...state, publicationUnknown: !state.committed && !refused(failure) }
        }
        throw failure
      }
      if (!current(b)) return null
      try { acceptPublication(b, response, sequence) }
      catch (failure) { state = { ...state, publicationUnknown: true }; throw failure }
      return await refreshPublication(b, abort)
    } catch (failure) { setError(b, failure); return null }
    finally {
      requests.delete(abort)
      if (binding === b) { applying = false; state = { ...state, busy: null }; emit() }
    }
  }
  function apply() {
    if (applyTask) return applyTask
    const task = doApply(); applyTask = task
    void task.finally(() => { if (applyTask === task) applyTask = null })
    return task
  }
  function publicationOperation(label, operation) {
    refreshContext()
    if (!binding || disposed || publicationTask || applying) return Promise.resolve(null)
    const b = binding, abort = new AbortController(); requests.add(abort)
    state = { ...state, busy: label, error: null }; emit()
    const task = (async () => {
      try { return await operation(b, abort) }
      catch (failure) { setError(b, failure); return null }
      finally { requests.delete(abort); if (current(b)) { state = { ...state, busy: null }; emit() } }
    })()
    publicationTask = task
    void task.finally(() => { if (publicationTask === task) publicationTask = null })
    return task
  }
  function resolvePublication() {
    return publicationOperation('status', async (b, abort) => {
      const publication = pendingPublication
      if (!publication || publication.binding !== b) return null
      const response = await api.status(body(b), options(b, abort))
      if (!current(b) || pendingPublication !== publication) return null
      envelope(b, response, publication.sequence)
      if (response.status === 'applied') {
        acceptPublication(b, response, publication.sequence)
        return refreshPublication(b, abort)
      }
      if (response.status === 'ready') {
        leaseDeadline(b, response, now())
        pendingPublication = null
        state = { ...state, publicationUnknown: false, error: error('Apply did not publish. Review the inputs before retrying') }; emit()
      } else if (!['applying', 'committing'].includes(response.status)) throw error('Publication status has not been confirmed')
      return response
    })
  }
  async function cancel() {
    const b = binding
    if (!b || !state.open) return null
    if (applying || state.publicationUnknown || state.committed) {
      try {
        const response = await api.cancel(body(b), options(b))
        if (!current(b)) return null
        if (response.status === 'applied') {
          acceptPublication(b, response, pendingPublication?.sequence ?? state.committed?.request_sequence)
          if (!applying && !publicationTask) return publicationOperation('refresh', refreshPublication)
          return response
        }
        if (['commit_in_progress', 'applying', 'committing'].includes(response.status)) return response
        if (response.status !== 'cancelled') throw error('Cancellation has not been confirmed')
      } catch (failure) { setError(b, failure); return null }
    }
    invalidate(); return null
  }
  return {
    open, openCreation, update, apply, cancel, resolvePublication, refreshContext,
    refreshCommitted: () => publicationOperation('refresh', refreshPublication),
    getState: snapshot,
    subscribe(listener) { listeners.add(listener); listener(snapshot()); return () => listeners.delete(listener) },
    dispose() {
      if (disposed) return
      invalidate(); disposed = true; unsubscribe?.(); listeners.clear()
      events?.removeEventListener('nadoc:document-reset', reset)
    },
  }
}
