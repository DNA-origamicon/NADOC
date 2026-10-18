import { cloneRepairInput, numericalRepairReviewRequired, repairActions, repairGuards, repairIssues, repairJobView,
  repairPublishedStatus, sameRepairContext } from './part_repair_model.js'

/** One input-only repair workflow shared by desktop and future VR adapters. */
export function createPartRepairController({ api, getContext, subscribeContext = () => () => {},
  events = globalThis.window, pollMs = 500, readyPollMs = 5000 }) {
  let context = getContext(), epoch = 0, disposed = false, adopting = false, timer = null, pollingJob = null
  let state = { draft: null, loaded: false, summary: context?.summary ?? null,
    job: null, inputs: null, busy: null, error: null, issues: [], committed: null, refreshNeeded: false, publication: null }
  const listeners = new Set(), requests = new Set()
  const snapshot = () => ({ ...state, context, ...repairJobView(state.job, context, state.draft),
    publishedStatus: repairPublishedStatus(state.job, context), requiresReview: numericalRepairReviewRequired(state.draft) })
  const emit = () => { if (!disposed) for (const listener of listeners) listener(snapshot()) }
  const stopTimer = () => { clearTimeout(timer); timer = null }
  function discardJob(job) {
    if (job?.id) Promise.resolve(api.cancel(job.id, { context: job.context })).catch(() => {})
  }
  function invalidate() {
    epoch++; stopTimer()
    for (const abort of requests) abort.abort()
    requests.clear()
    const old = state.job
    state = { draft: null, loaded: false, summary: getContext()?.summary ?? null,
      job: null, inputs: null, busy: null, error: null, issues: [], committed: null, refreshNeeded: false, publication: null }
    context = getContext(); discardJob(old); emit()
  }
  function refreshContext() {
    if (disposed || adopting) return
    const next = getContext()
    if (!sameRepairContext(context, next)) invalidate()
    else if (next?.summary !== state.summary) { state = { ...state, summary: next?.summary ?? null }; emit() }
  }
  const unsubscribe = subscribeContext(refreshContext)
  events?.addEventListener('nadoc:document-reset', invalidate)
  const current = token => !disposed && token.epoch === epoch && sameRepairContext(token.context, getContext())

  async function run(label, operation, { mutate = false, preserveJob = false } = {}) {
    refreshContext()
    if (disposed || state.busy) return null
    const token = { epoch, context: { ...context } }, abort = new AbortController()
    requests.add(abort)
    try {
      repairGuards(context, state.draft)
      if (state.publication && label !== 'resolve-publication') {
        throw new Error('Publication status is unknown. Check publication status before continuing')
      }
      if (state.refreshNeeded && !['refresh', 'apply'].includes(label)) {
        throw new Error('The proposal is published. Refresh the committed result before continuing')
      }
      if (mutate && (!context.editable || context.cursor !== -1 || context.subCursor != null)) {
        throw new Error('Choose the current editable part loadout to change its repair proposal')
      }
      if (mutate && !preserveJob) { discardJob(state.job); stopTimer(); state = { ...state, job: null } }
      state = { ...state, busy: label, error: null, issues: state.job ? repairIssues(state.job.response?.result) : [] }; emit()
      return await operation(token, { context: token.context, signal: abort.signal })
    } catch (error) {
      if (current(token) || (token.adopted && token.epoch === epoch && !disposed && sameRepairContext(context, getContext()))) {
        state = { ...state, error, issues: repairIssues(error), job: preserveJob && state.job?.response ? null : state.job }; emit()
      }
      return null
    } finally {
      requests.delete(abort)
      if (current(token)) { state = { ...state, busy: null }; emit() }
      // Metadata acceptance deliberately changes our own revision without
      // cancelling the request that just published it.
      else if (!disposed && token.epoch === epoch && state.busy === label) {
        state = { ...state, busy: null }; emit()
      }
    }
  }

  function adoptMetadata(result, token, { keepDraft = false, inspection = false } = {}) {
    if (!current(token)) return null
    if (inspection && result.revision !== token.context.revision) {
      throw new Error('The published design changed. Refresh the design before inspecting its repair proposal')
    }
    const draft = keepDraft ? state.draft : cloneRepairInput(result.draft)
    adopting = true
    try {
      if (api.acknowledge(result, token.context) === false) throw new Error('The repair response belongs to an older document state')
      discardJob(state.job); stopTimer()
      context = getContext()
      token.adopted = true
      state = { ...state, draft, loaded: true,
        summary: result.repair_draft ?? null, job: null, inputs: null, issues: [], committed: null, refreshNeeded: false, publication: null }
      emit(); return result
    } finally { adopting = false }
  }

  function schedule(delay = pollMs) {
    stopTimer()
    if (!disposed && state.job) timer = setTimeout(() => { timer = null; void poll() }, delay)
  }
  async function poll() {
    refreshContext()
    if (disposed || !state.job || pollingJob === state.job.id) return null
    stopTimer()
    const job = state.job, token = { epoch, context: job.context }, abort = new AbortController()
    pollingJob = job.id; requests.add(abort)
    try {
      const response = await api.poll(job.id, { context: job.context, signal: abort.signal })
      if (!current(token) || state.job?.id !== job.id) return null
      // Candidate geometry is never retained in this browser workflow, even
      // if a future server accidentally includes it in a status response.
      const { candidate: _candidate, ...result } = response.result ?? {}
      const { candidate: _topLevelCandidate, ...status } = response
      state = { ...state, job: { ...job, response: { ...status, result: response.result ? result : null } },
        error: null, issues: repairIssues(result) }; emit()
      if (response.stale) discardJob(job)
      else if (response.status === 'running' || response.source_busy) schedule()
      else if (repairJobView(state.job, context, state.draft).ready) schedule(readyPollMs)
      return response
    } catch (error) {
      if (current(token) && state.job?.id === job.id) {
        state = { ...state, job: { ...job, response: null }, error, issues: repairIssues(error) }; emit()
      }
      return null
    } finally { requests.delete(abort); if (pollingJob === job.id) pollingJob = null }
  }

  async function startJob(operation, payload, token, options) {
    discardJob(state.job); stopTimer(); state = { ...state, job: null }
    const draft = state.draft
    const response = operation === 'repair' ? await api.evaluate(payload, options) : await api.start(payload, options)
    const job = { id: response.job_id, operation, context: token.context, response: null,
      draftId: draft?.draft_id, generation: draft?.generation }
    if (!current(token)) { discardJob(job); return null }
    if (operation === 'repair' && (response.repair_draft?.draft_id !== draft?.draft_id
        || response.repair_draft?.generation !== draft?.generation)) {
      discardJob(job); throw new Error('The evaluation belongs to a different proposal generation')
    }
    state = { ...state, job }; emit(); schedule(0)
    return response
  }

  const mutate = (operation, actions) => run(operation, async (token, options) => {
    if (!state.loaded) throw new Error('Open the saved proposal before changing it')
    const body = { ...repairGuards(token.context, state.draft), operation }
    if (actions !== undefined) body.actions = repairActions(actions)
    return adoptMetadata(await api.mutate(body, options), token)
  }, { mutate: true })

  async function refreshPublication(token, options) {
    const receipt = state.committed
    if (!receipt) throw new Error('No committed result is awaiting display')
    const result = await api.refreshCommitted(receipt, options)
    if (!current(token) || state.committed !== receipt) return null
    adopting = true
    let applied
    try {
      applied = api.apply(result, token.context)
      context = getContext(); token.adopted = true
    } finally { adopting = false }
    await applied
    if (disposed || token.epoch !== epoch || !sameRepairContext(context, getContext()) || state.committed !== receipt) return null
    state = { ...state, refreshNeeded: false,
      summary: state.summary ? { ...state.summary, base_status: 'rebase_required' } : null }
    emit(); return result
  }

  function acceptPublication(receipt, publication) {
    if (receipt.job_id !== publication.jobId || receipt.status !== 'committed'
        || receipt.design_id !== publication.context.designId || receipt.revision !== publication.context.revision + 1) {
      state = { ...state, publication: { ...publication, outcome: 'unknown' } }; emit()
      throw new Error('The server returned an unexpected receipt. Check publication status before continuing')
    }
    state = { ...state, publication: null, committed: cloneRepairInput(receipt), refreshNeeded: true, inputs: null }
    emit()
  }

  return {
    getState: snapshot,
    subscribe(listener) { listeners.add(listener); listener(snapshot()); return () => listeners.delete(listener) },
    refreshContext,
    inspect: () => run('inspect', async (token, options) => adoptMetadata(await api.inspect(options), token, { inspection: true })),
    inspectInputs: target => run('inputs', async (token, options) => {
      state = { ...state, inputs: null }; emit()
      const result = await api.inspectInputs({ expected_design_id: token.context.designId,
        expected_revision: token.context.revision, feature_id: target.feature_id, child_id: target.child_id ?? null }, options)
      if (!current(token)) return null
      if (result.version !== 1 || result.assessment !== 'inputs_only' || result.design_id !== token.context.designId
          || result.revision !== token.context.revision || result.feature_id !== target.feature_id
          || (result.child_id ?? null) !== (target.child_id ?? null)) throw new Error('The input catalog belongs to another feature or revision')
      state = { ...state, inputs: result }; emit(); return result
    }),
    save: actions => mutate(state.draft ? 'update' : 'create', actions),
    rebase: actions => mutate('rebase', actions),
    discard: () => mutate('discard'),
    check: () => run('check', (token, options) => startJob('verify',
      { operation: 'verify', expected_revision: token.context.revision }, token, options)),
    evaluate: () => run('evaluate', (token, options) => {
      if (!state.loaded || !state.draft) throw new Error('Save a repair proposal before evaluating it')
      if (numericalRepairReviewRequired(state.draft)) throw new Error('Numerical contract changes require the separate atom and junction comparison review')
      return startJob('repair', repairGuards(token.context, state.draft), token, options)
    }, { mutate: true }),
    selectReferences: selection => run('selection', (token, options) => startJob('selection', {
      operation: 'selection', expected_revision: token.context.revision,
      selection: { ...cloneRepairInput(selection), selection_version: 1,
        expected_design_id: token.context.designId, expected_revision: token.context.revision },
    }, token, options)),
    inspectSource: selection => run('inspect-source', async (token, options) => {
      if (!state.draft) throw new Error('Save a proposal before selecting its source input')
      const { draft_version: _version, ...guards } = repairGuards(token.context, state.draft)
      const result = await api.inspectSource({ ...cloneRepairInput(selection), ...guards, source_repair_version: 1 }, options)
      return current(token) ? result : null
    }),
    uploadSource: (receipt, file) => run('upload-source', async (token, options) => {
      const result = await api.uploadSource(receipt, file, options)
      return adoptMetadata(result, token, { keepDraft: true })
    }, { mutate: true }),
    cancel() {
      const job = state.job
      epoch++; stopTimer()
      for (const abort of requests) abort.abort()
      requests.clear(); state = { ...state, busy: null, job: null, error: null, issues: [],
        publication: state.publication ? { ...state.publication, outcome: 'unknown' } : null }
      discardJob(job); emit()
    },
    apply: () => run('apply', async (token, options) => {
      if (state.refreshNeeded) throw new Error('The proposal is already published. Refresh the committed result')
      if (!repairJobView(state.job, token.context, state.draft).ready || numericalRepairReviewRequired(state.draft)) throw new Error('Evaluate and review the current proposal before applying it')
      stopTimer()
      const job = state.job, publication = { jobId: job.id, context: token.context, outcome: 'pending' }
      // Once publication starts, cancellation must not imply the candidate is
      // still private. A successful receipt is retained even if display fails.
      state = { ...state, job: null, publication }; emit()
      let result
      try { result = await api.commit(job.id, options) } catch (error) {
        if (current(token)) {
          // These documented HTTP refusals occur before publication. Network,
          // server and malformed-response failures cannot establish that fact.
          const refused = [403, 404, 409, 410, 413, 422, 429].includes(error.status)
          state = { ...state, publication: refused ? null : { ...publication, outcome: 'unknown' },
            job: refused ? { ...job, response: null } : null }
          emit()
        }
        throw error
      }
      if (!current(token)) return null
      acceptPublication(result, publication)
      return refreshPublication(token, options)
    }, { mutate: true, preserveJob: true }),
    refreshCommitted: () => run('refresh', refreshPublication, { preserveJob: true }),
    resolvePublication: () => run('resolve-publication', async (token, options) => {
      const publication = state.publication
      if (!publication) throw new Error('No publication status is awaiting confirmation')
      const result = await api.poll(publication.jobId, { ...options, context: publication.context })
      if (!current(token) || state.publication !== publication) return null
      if (result.status !== 'committed' || result.job_id !== publication.jobId || result.stale !== false || result.source_busy !== false) {
        throw new Error('Publication has not been confirmed. Check status again or reload the current design')
      }
      acceptPublication({ job_id: result.job_id, status: result.status, revision: result.revision,
        design_id: publication.context.designId }, publication)
      return refreshPublication(token, options)
    }, { preserveJob: true }),
    poll,
    dispose() {
      if (disposed) return
      invalidate(); disposed = true; unsubscribe?.(); listeners.clear()
      events?.removeEventListener('nadoc:document-reset', invalidate)
    },
  }
}
