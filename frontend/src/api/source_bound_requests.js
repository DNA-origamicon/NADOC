/** One source-bound publication path for native tools with complete geometry. */
export function createSourceBoundRequests({ store, request, syncDesign, getDocId, currentRevision,
  documentRequests, label = 'feature', requireRevision = true }) {
  const capture = (state = store.getState()) => Object.freeze({ source: state.currentDesign,
    designId: state.currentDesign?.id, revision: currentRevision(), docId: getDocId(),
    generation: documentRequests.capture() })
  const sameDocument = context => context && documentRequests.isCurrent(context.generation)
    && getDocId() === context.docId && !store.getState().assemblyActive
  const isCurrent = (context, state = store.getState()) => sameDocument(context)
    && state.currentDesign === context.source && currentRevision() === context.revision
  const stale = () => new Error(`The part changed. Reopen the ${label} tool on the current part.`)
  async function send(path, body, context) {
    if (!isCurrent(context) || !context.designId) throw stale()
    if ((requireRevision || context.source.group_organization)
        && (!Number.isSafeInteger(context.revision) || context.revision < 0))
      throw new Error(`Refresh the current part before creating or editing this ${label}.`)
    const response = await request('POST', path, { ...body,
      expected_design_id: context.designId, expected_revision: context.revision,
    }, { docId: context.docId, protectedRetry: false, skipSimulationPrepare: true })
    if (!isCurrent(context)) throw stale()
    if (!response) throw new Error(store.getState().lastError?.message || `No confirmed ${label} result; refresh before retrying.`)
    if (response.design?.id !== context.designId || !Number.isSafeInteger(response.revision)
        || (context.revision != null && response.revision <= context.revision)) throw stale()
    // A lean response would make synchronization fetch unbound later geometry.
    if (!Array.isArray(response.nucleotides) || response.partial_geometry || response.geometry_skipped
        || response.diff_kind === 'cluster_only' || response.diff_kind === 'positions_only')
      throw new Error(`The ${label} response has no complete geometry. Refresh the part before continuing.`)
    const adopted = await syncDesign(response)
    if (!adopted || !sameDocument(context) || store.getState().currentDesign !== response.design
        || currentRevision() !== response.revision)
      throw new Error(`The ${label} response was not accepted by the current part.`)
    return response
  }
  return { capture, isCurrent, send,
    edit(index, params, context, featureId) {
      if (!Number.isSafeInteger(index) || index < 0 || !featureId
          || context?.source?.feature_log?.[index]?.id !== featureId)
        return Promise.reject(new Error(`The ${label} feature changed. Reopen its editor.`))
      return send(`/design/features/${index}/edit`, { params, expected_feature_id: featureId }, context)
    },
  }
}
