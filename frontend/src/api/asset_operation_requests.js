import { attributeFailure } from '../features/feature_history_failure.js'

/** Ordinary asset commands and history edits share the existing recipe jobs. */
export function createAssetOperationRequests({ store, request, transport, getDocId, currentRevision,
  documentRequests, syncDesign, showProgress, saves, pollMs = 200, events = globalThis.window }) {
  let active = null
  const capture = () => {
    const source = store.getState().currentDesign
    return { source, designId: source?.id, loadoutId: source?.active_loadout_id ?? null,
      docId: getDocId(), revision: currentRevision(), generation: documentRequests.capture() }
  }
  const current = context => {
    const state = store.getState(), design = state.currentDesign
    // Autosave and display metadata reads replace the frontend object without
    // changing its authoring revision. The server separately owns the exact
    // source/session guard; use the same revision/loadout identity as repair.
    return documentRequests.isCurrent(context.generation) && getDocId() === context.docId
      && currentRevision() === context.revision && design?.id === context.designId
      && (design?.active_loadout_id ?? null) === context.loadoutId && !state.assemblyActive
      && (design?.feature_log_cursor ?? -1) === -1 && design?.feature_log_sub_cursor == null
      && !design?.loadouts?.find(item => item.id === context.loadoutId)?.protected
  }
  const discard = operation => {
    if (operation.jobId && !operation.publishing)
      Promise.resolve(transport.cancel(operation.jobId, { context: operation.context })).catch(() => {})
  }
  function guard(context) {
    const source = context.source, loadout = source?.loadouts?.find(item => item.id === context.loadoutId)
    if (!current(context) || !source || !Number.isSafeInteger(context.revision) || context.revision < 0
        || loadout?.protected || (source.feature_log_cursor ?? -1) !== -1 || source.feature_log_sub_cursor != null
        || store.getState().featureSeekPending) throw new Error('Return to the current editable part before editing an asset.')
  }
  const stale = () => new Error('The part changed. Reopen the asset tool.')
  const publicationCurrent = operation => operation.publishing
    && current({ ...operation.context, revision: operation.context.revision + 1 })
  const operationCurrent = operation => current(operation.context) || publicationCurrent(operation)
  function check(operation) {
    if (operation.invalidated) throw stale()
    if (operation.cancelled) throw new DOMException('Asset operation cancelled. The part is unchanged.', 'AbortError')
    if (!operationCurrent(operation)) throw stale()
  }
  async function refresh(operation) {
    check(operation)
    if (!operation.receipt) {
      const status = await transport.poll(operation.jobId, { context: operation.context })
      check(operation)
      if (status.status !== 'committed' || status.job_id !== operation.jobId || status.stale !== false
          || status.source_busy !== false || status.revision !== operation.context.revision + 1)
        throw new Error('Publication is not confirmed. Refresh the part before starting another asset operation.')
      operation.receipt = { job_id: operation.jobId, status: 'committed', revision: status.revision,
        design_id: operation.context.designId }
    }
    const result = await transport.refreshCommitted(operation.receipt, { context: operation.context })
    check(operation)
    operation.adopting = true
    // A background read may already have adopted this publication's revision.
    // refreshCommitted has independently checked the receipt, live revision,
    // geometry and the same committed job before this context can advance.
    await transport.apply(result, { ...operation.context, revision: currentRevision() })
    operation.view?.close(); operation.finished = true
    operation.unsubscribe?.(); events?.removeEventListener('nadoc:document-reset', operation.invalidate)
    if (active === operation) active = null
    operation.releaseSave?.()
    return { ...result, ...(operation.generation ? { generation: operation.generation } : {}),
      ...(operation.append?.nanoparticle_id ? { nanoparticle_id: operation.append.nanoparticle_id } : {}) }
  }
  async function run(start, { label = 'Updating nanoparticle', context, featureId } = {}) {
    if (active) throw new Error('Finish or refresh the current asset operation first.')
    const initial = capture(), saveHold = context?.editorSaveHold ?? saves?.hold()
    const releaseSave = () => { if (!context?.editorSaveHold) saveHold?.release() }
    if (saveHold) await saveHold.ready
    context ??= capture()
    try {
      if (active) throw new Error('Finish or refresh the current asset operation first.')
      if (context.designId !== initial.designId || context.docId !== initial.docId
          || !documentRequests.isCurrent(initial.generation)) throw stale()
      guard(context)
    } catch (error) { releaseSave(); throw error }
    const operation = { context, jobId: null, cancelled: false, publishing: false, adopting: false }
    operation.releaseSave = releaseSave
    active = operation
    operation.invalidate = () => {
      if (operation.adopting) return
      operation.invalidated = true; operation.cancelled = true; discard(operation); operation.view?.close()
      operation.unsubscribe?.(); events?.removeEventListener('nadoc:document-reset', operation.invalidate)
      if (active === operation) active = null
      releaseSave()
    }
    operation.unsubscribe = store.subscribe(() => { if (!operationCurrent(operation)) operation.invalidate() })
    events?.addEventListener('nadoc:document-reset', operation.invalidate)
    try {
      const started = await start(context)
      operation.jobId = started?.job_id
      check(operation)
      if (!operation.jobId) {
        if (!started?.design) throw new Error('The asset operation returned no confirmed result.')
        operation.adopting = true
        await syncDesign(started)
        return started
      }
      if (started.source_revision !== context.revision) throw stale()
      operation.view = showProgress({ title: label, cancel: () => { operation.cancelled = true; discard(operation) } })
      operation.view.update('Regenerating from saved inputs…')
      let response
      do {
        check(operation)
        response = await transport.poll(operation.jobId, { context })
        check(operation)
        if (response.job_id !== operation.jobId || response.stale) throw stale()
        if (response.status === 'running') await new Promise(resolve => setTimeout(resolve, pollMs))
      } while (response.status === 'running')
      if (response.result?.status !== 'ready' || response.source_busy) {
        const issue = response.result?.issues?.[0]
        const detail = issue?.code === 'evaluation_rejected' && typeof issue.detail === 'object' ? issue.detail : issue
        throw Object.assign(new Error(typeof detail?.detail === 'string' ? detail.detail : 'This asset operation cannot regenerate.'),
          { detail: { assessment: response.result, feature_id: detail?.feature_id }, code: detail?.code })
      }
      operation.append = response.result.append
      operation.generation = response.result.generation
      check(operation); operation.publishing = true
      operation.view.update('Applying…', { committing: true })
      try { operation.receipt = await transport.commit(operation.jobId, { context }) }
      catch (error) {
        if ([403, 404, 409, 410, 413, 422, 429].includes(error.status)) { operation.publishing = false; throw error }
        // A lost reply is resolved by observing the same job, never resubmitting.
      }
      return await refresh(operation)
    } catch (error) {
      if (operation.publishing && !operation.cancelled && operationCurrent(operation)) {
        const retry = async () => {
          try { await refresh(operation) }
          catch (next) { operation.view.update(next.message, { committing: true, refresh: retry }) }
        }
        operation.view?.update('The save may be complete. Refresh its result before continuing.', { committing: true, refresh: retry })
      } else { discard(operation); operation.view?.close() }
      throw attributeFailure(error, context.source, featureId)
    } finally {
      if (!operation.publishing || operation.finished || operation.cancelled || !operationCurrent(operation)) {
        operation.unsubscribe?.(); events?.removeEventListener('nadoc:document-reset', operation.invalidate)
        if (active === operation) active = null
        releaseSave()
      }
    }
  }
  return {
    capture, isCurrent: current,
    async beginEdit() {
      const initial = capture(), hold = saves?.hold()
      try {
        if (hold) await hold.ready
        const context = capture()
        if (context.designId !== initial.designId || context.docId !== initial.docId
            || !documentRequests.isCurrent(initial.generation)) throw stale()
        guard(context)
        return { ...context, editorSaveHold: hold }
      } catch (error) { hold?.release(); throw error }
    },
    endEdit(context) {
      if (active?.context === context && active.publishing)
        active.releaseSave = () => context?.editorSaveHold?.release()
      else context?.editorSaveHold?.release()
    },
    ordinary(method, path, body, options) {
      return run(async context => {
        const query = new URLSearchParams({ expected_revision: context.revision, expected_design_id: context.designId })
        let failure
        const result = await request(method, `${path}?${query}`, body, { docId: context.docId,
          protectedRetry: false, skipSimulationPrepare: true,
          onError: (status, detail) => { failure = Object.assign(new Error(typeof detail === 'string' ? detail : detail?.detail ?? 'Asset operation failed.'), { status, detail }) } })
        if (failure) throw failure
        return result
      }, options)
    },
    edit(index, params, context, featureId, label) {
      if (context?.source?.feature_log?.[index]?.id !== featureId) return Promise.reject(stale())
      return run(ctx => transport.start({ operation: 'edit', index, params, expected_revision: ctx.revision }, { context: ctx }),
        { context, featureId, label })
    },
  }
}
