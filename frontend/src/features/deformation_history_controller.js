import { validatePreviewComputation } from '../api/preview_computation.js'
import { cloneRepairInput, sameRepairContext } from './part_repair_model.js'
import { DeformationPreviewRequestError, previewFamilyIdentity, previewPublicationReceipt } from '../api/deformation_preview_endpoints.js'

const CONTEXT = ['docId', 'designId', 'revision', 'loadoutId', 'editable', 'cursor', 'subCursor']
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const refused = error => [403, 404, 408, 409, 410, 413, 422, 429].includes(error?.status)
const error = (message, status = 409) => new DeformationPreviewRequestError(status, message)
const empty = family => ({ mode: 'edit', awaitingParameters: false, open: false, busy: null, featureId: null,
  ...(family === 'transform' ? { family, commandKind: null } : { deformationId: null }),
  draft: {}, projection: null, controls: null, error: null, expired: false, computation: null,
  committed: null, refreshNeeded: false, publicationUnknown: false })
const contextCopy = context => Object.fromEntries(CONTEXT.map(key => [key, context?.[key]]))

/** Owns one private editor. Only applyPublished may adopt a canonical response. */
export function createDeformationHistoryController({ api, getContext, subscribeContext = () => () => {},
  validateDisplay, applyPublished, family = 'deformation', events = globalThis.window,
  uuid = () => crypto.randomUUID(), now = () => performance.now() }) {
  if (!['deformation', 'sweep', 'transform'].includes(family)) throw new Error('Unsupported feature preview family')
  if (typeof validateDisplay !== 'function' || typeof applyPublished !== 'function') {
    throw new Error('Preview display validation and publication adoption are required')
  }
  let state = empty(family), binding = null, epoch = 0, disposed = false, adopting = false, timer = null
  let active = null, pending = null, applyTask = null, publicationTask = null, applying = false
  let draftVersion = 0, evaluatedVersion = 0, pendingPublication = null
  const requests = new Set(), listeners = new Set()
  const snapshot = () => ({ ...state, draft: cloneRepairInput(state.draft),
    computation: state.computation ? { ...state.computation } : null,
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
    state = empty(family); cleanup(old); emit()
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
    state = { ...state, expired: true, projection: null, busy: null, computation: null,
      error: error('The preview expired. Reopen this feature to continue') }
    // An in-flight Apply may have published despite a lost/aborted response.
    if (pendingPublication) state.publicationUnknown = true
    cleanup(b); emit()
  }
  function leaseDeadline(b, response, started, timing = null) {
    const seconds = response.remaining_seconds
    if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0 || seconds > 60) {
      throw error('The preview lease response is invalid', 422)
    }
    const readStart = timing ? timing.receivedAt - timing.elapsedMs : started
    const deadline = readStart + seconds * 1000
    b.deadline = timing?.renewed ? deadline : Math.min(b.deadline, deadline)
    stopTimer()
    if (b.deadline <= now()) { expire(b); throw error('The preview expired. Reopen this feature to continue') }
    timer = setTimeout(() => expire(b), b.deadline - now())
  }
  function envelope(b, response, sequence, { opening = false } = {}) {
    if (!response || Object.entries(b.origin).some(([key, value]) => response[key] !== value)
        || response.doc_id !== (b.context.docId ?? '__default__')
        || !UUID.test(response.lease_id ?? '') || (!opening && response.lease_id !== b.lease)
        || response.request_sequence !== sequence) throw error('The preview response belongs to another feature or revision')
    previewFamilyIdentity(response, family, opening ? null : b.identity)
  }
  function computationOptions(b, abort, operation, sequence, { opening = false } = {}) {
    const tracking = { timing: null }
    const expected = () => ({ body: { ...body(b), request_sequence: sequence }, context: b.context,
      operation, expectedIdentity: b.identity,
      identity: (value, expectedIdentity) => previewFamilyIdentity(value, family, expectedIdentity),
      error: (status, detail) => new DeformationPreviewRequestError(status, detail) })
    tracking.options = { ...options(b, abort),
      computation: { operation, request_sequence: sequence, identity: b.identity },
      onComputation(value) {
        if (family !== 'transform' || !current(b)
            || (state.expired && !(operation === 'apply' && state.publicationUnknown))) throw error('The computation is no longer current')
        envelope(b, value, sequence, { opening })
        const identity = validatePreviewComputation(value, expected())
        if (!(operation === 'prepare' ? value.status === 'preparing' : ['applying', 'committing'].includes(value.status))) {
          throw error('Invalid active computation', 422)
        }
        b.lease = value.lease_id; b.identity = identity
        // The ready timer is suspended only after the server acknowledges this
        // exact Apply. Transport silence alone cannot extend its authority.
        if (operation === 'apply') stopTimer()
        state = { ...state, commandKind: identity.command_kind, computation: { ...value.computation } }; emit()
      },
      onReadTiming(value) {
        if (!current(b)) return
        if (!value || !Number.isFinite(value.elapsedMs) || value.elapsedMs < 0
            || typeof value.renewed !== 'boolean') throw error('Invalid local response timing', 422)
        if (value.renewed) {
          envelope(b, value.response, sequence, { opening })
          validatePreviewComputation(value.response, expected())
        }
        // This callback is invoked by transport code, never read from JSON.
        tracking.timing = { elapsedMs: value.elapsedMs, receivedAt: now(), renewed: value.renewed, response: value.response }
      },
    }
    return tracking
  }
  function knownFailure(b, failure, tracking, started, { statusRead = false } = {}) {
    if (!current(b)) return
    const known = failure.computationFailure || (!statusRead && refused(failure) && !failure.publicationUnknown)
    if (known) pendingPublication = null
    if (failure.computationFailure && tracking.timing?.renewed) {
      // An expired local display stays expired; a fresh server lease alone
      // cannot restore geometry already released on this client.
      leaseDeadline(b, tracking.timing.response, started, tracking.timing)
    }
    state = { ...state, computation: null, publicationUnknown: !state.committed && !known }
  }
  function available() {
    refreshContext()
    if (!binding || !state.open || !state.projection || disposed || state.expired || !binding.lease || state.committed || state.publicationUnknown
        || state.computation || state.busy === 'prepare') return false
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
    if (creation && family !== 'deformation') {
      state = { ...state, error: error('This history editor does not create new features', 422) }; emit(); return null
    }
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
      expected_revision: context.revision, feature_id: featureId }, lease: null, identity: null, sequence: 0, deadline: Infinity }
    b.mode = creation ? 'create' : 'edit'
    binding = b; draftVersion = 0; evaluatedVersion = creation ? -1 : 0
    state = { ...empty(family), mode: b.mode, awaitingParameters: !!creation, open: true, featureId, busy: 'prepare' }; emit()
    const abort = new AbortController(), started = now(); requests.add(abort)
    const tracking = computationOptions(b, abort, 'prepare', 0, { opening: true })
    try {
      const response = creation
        ? await api.prepareCreation({ ...body(b), mode: 'create', ...creation }, options(b, abort))
        : await api.prepare(body(b), tracking.options)
      if (!current(b)) {
        try { envelope(b, response, 0, { opening: true }); cleanup(b, response.lease_id) } catch { /* original nonce cancellation remains authoritative */ }
        return null
      }
      envelope(b, response, 0, { opening: true })
      displayMode(b, response, true)
      validateDisplay(response, { prepare: true })
      evaluatedRole(response, {})
      b.lease = response.lease_id; b.identity = previewFamilyIdentity(response, family)
      if (family === 'deformation' && Array.isArray(response.before?.nucleotides?.rows)) {
        b.displayRows = Object.freeze(response.before.nucleotides.rows.map(row => Object.freeze([...row])))
      }
      leaseDeadline(b, response, started, tracking.timing)
      state = { ...state, computation: null, ...(family === 'transform' ? { commandKind: b.identity.command_kind } : { deformationId: b.identity.deformation_id }),
        projection: response, controls: response.control_context, error: null }
      emit(); return response
    } catch (failure) { setError(b, failure); return null }
    finally { requests.delete(abort); if (current(b)) { state = { ...state, busy: null, computation: null }; emit() } }
  }

  function openCreation({ type, targets, clusterIds } = {}) {
    try {
      if (family !== 'deformation') throw error('This history editor does not create new features', 422)
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
  function evaluatedRole(response, draft) {
    if (family !== 'transform') return
    const expected = response.command_kind === 'cluster_op' && draft.upgrade_to === 'placement-poses-v1'
      ? 'placement-poses' : response.command_kind
    if (response.evaluated_command_kind !== expected) throw error('The evaluated transform role differs from the requested draft', 422)
  }

  async function evaluate(entry) {
    const b = entry.binding, abort = new AbortController(), started = now()
    requests.add(abort)
    state = { ...state, busy: applying ? 'apply' : 'evaluate' }; emit()
    try {
      const response = await api.evaluate({ ...body(b), request_sequence: nextSequence(b),
        params: entry.draft, include_geometry: entry.includeGeometry,
        ...(family === 'deformation' && b.displayRows ? { reuse_rows: true } : {}) }, options(b, abort))
      if (!current(b) || state.expired || entry.version !== draftVersion) return null
      envelope(b, response, b.sequence)
      displayMode(b, response, false)
      // Resolve only after document, lease and request-sequence checks. A delta
      // can refer solely to the validated preparation of this exact editor.
      const packed = response.candidate?.nucleotides
      if (family === 'deformation' && packed && Object.hasOwn(packed, 'rows_ref')) {
        if (packed.rows_ref !== b.lease || !Array.isArray(b.displayRows)
            || Object.hasOwn(packed, 'rows') || packed.count !== b.displayRows.length) {
          throw error('The preview topology belongs to another session', 422)
        }
        const { rows_ref, ...coordinates } = packed
        response.candidate.nucleotides = { ...coordinates, rows: b.displayRows }
      }
      validateDisplay(response, { prepare: false })
      evaluatedRole(response, entry.draft)
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
  function queueDraft(patch, { includeGeometry = true } = {}, replace = false) {
    if (!available() || applying || publicationTask) return Promise.resolve(null)
    try {
      const copy = cloneRepairInput(patch)
      if (!copy || Array.isArray(copy) || typeof copy !== 'object' || typeof includeGeometry !== 'boolean') {
        throw error('Preview changes must be an input object', 422)
      }
      state = { ...state, draft: cloneRepairInput(replace ? copy : { ...state.draft, ...copy }), error: null }
      draftVersion++; discardPending()
      const promise = new Promise(resolve => { pending = { binding, version: draftVersion,
        draft: cloneRepairInput(state.draft), includeGeometry, resolve } })
      emit(); pump(); return promise
    } catch (failure) { setError(binding, failure); return Promise.resolve(null) }
  }
  const update = (patch, options) => queueDraft(patch, options)
  const resetDraft = options => queueDraft({}, options, true)

  function acceptPublication(b, response, sequence) {
    // Preserve legacy small-receipt enrichment. Transform receipts always
    // carry their full origin and declared role; missing fields cannot acquire
    // publication authority from the editor's retained binding.
    const complete = family === 'transform' ? response : { ...b.origin, ...b.identity, ...response }
    envelope(b, complete, sequence)
    const receipt = previewPublicationReceipt(complete, b.context, null, { family })
    if (state.committed) {
      previewPublicationReceipt(receipt, b.context, state.committed, { family })
      return state.committed
    }
    pendingPublication = null; stopTimer()
    state = { ...state, committed: receipt, computation: null, publicationUnknown: false, refreshNeeded: true, error: null }
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
      const started = now(), tracking = computationOptions(b, abort, 'apply', sequence)
      let response
      try {
        response = await api.apply({ ...body(b), request_sequence: sequence, params: cloneRepairInput(state.draft) }, tracking.options)
      } catch (failure) {
        knownFailure(b, failure, tracking, started)
        throw failure
      }
      if (!current(b)) return null
      try { acceptPublication(b, response, sequence) }
      catch (failure) { state = { ...state, publicationUnknown: !state.committed }; throw failure }
      return await refreshPublication(b, abort)
    } catch (failure) { setError(b, failure); return null }
    finally {
      requests.delete(abort)
      if (binding === b) { applying = false; state = { ...state, busy: null, computation: null }; emit() }
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
      finally { requests.delete(abort); if (current(b)) { state = { ...state, busy: null, computation: null }; emit() } }
    })()
    publicationTask = task
    void task.finally(() => { if (publicationTask === task) publicationTask = null })
    return task
  }
  function resolvePublication() {
    return publicationOperation('status', async (b, abort) => {
      const publication = pendingPublication
      if (!publication || publication.binding !== b) return null
      const started = now(), tracking = computationOptions(b, abort, 'apply', publication.sequence)
      let response
      try { response = await api.status(body(b), tracking.options) }
      catch (failure) { knownFailure(b, failure, tracking, started, { statusRead: true }); throw failure }
      if (!current(b) || pendingPublication !== publication) return null
      envelope(b, response, publication.sequence)
      if (response.status === 'applied') {
        acceptPublication(b, response, publication.sequence)
        return refreshPublication(b, abort)
      }
      if (response.status === 'ready') {
        leaseDeadline(b, response, started, tracking.timing)
        pendingPublication = null
        state = { ...state, computation: null, publicationUnknown: false, error: error('Apply did not publish. Review the inputs before retrying') }; emit()
      } else if (!['applying', 'committing'].includes(response.status)) throw error('Publication status has not been confirmed')
      return response
    })
  }
  function cancellationAcknowledgement(b, response) {
    if (family !== 'transform') return
    // Backend cancellation acknowledges only the nonce (and lease while
    // committing). These acknowledgments cannot establish publication.
    const committing = ['commit_in_progress', 'applying', 'committing'].includes(response?.status)
    if (!response || response.preview_id !== b.origin.preview_id
        || (committing && response.lease_id !== b.lease)
        || (Object.hasOwn(response, 'lease_id') && response.lease_id !== b.lease)
        || Object.entries(b.origin).some(([key, value]) => Object.hasOwn(response, key) && response[key] !== value)) {
      throw error('Cancellation belongs to another preview')
    }
    if (['family', 'command_kind', 'deformation_id'].some(key => Object.hasOwn(response, key))) {
      previewFamilyIdentity(response, family, b.identity)
    }
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
        cancellationAcknowledgement(b, response)
        if (['commit_in_progress', 'applying', 'committing'].includes(response.status)) return response
        if (response.status !== 'cancelled') throw error('Cancellation has not been confirmed')
      } catch (failure) { setError(b, failure); return null }
    }
    invalidate(); return null
  }
  return {
    open, openCreation, update, resetDraft, apply, cancel, resolvePublication, refreshContext,
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
