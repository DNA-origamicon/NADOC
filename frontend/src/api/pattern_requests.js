/** Bind pattern publication to the document and source shown by the tool. */
export function createPatternRequests({ store, request, syncDesign, getDocId, currentRevision, documentRequests }) {
  const capture = (state = store.getState()) => Object.freeze({ source: state.currentDesign,
    designId: state.currentDesign?.id, revision: currentRevision(), docId: getDocId(),
    generation: documentRequests.capture() })
  const sameDocument = context => context && documentRequests.isCurrent(context.generation)
    && getDocId() === context.docId && !store.getState().assemblyActive
  const isCurrent = (context, state = store.getState()) => sameDocument(context)
    && state.currentDesign === context.source && currentRevision() === context.revision
  const stale = () => new Error('The part changed. Reopen the pattern tool on the current part.')
  async function send(path, body, context) {
    if (!isCurrent(context) || !context.designId) throw stale()
    if (context.source.group_organization && (!Number.isSafeInteger(context.revision) || context.revision < 0))
      throw new Error('Refresh the current part before creating or editing a pattern.')
    const response = await request('POST', path, { ...body,
      expected_design_id: context.designId, expected_revision: context.revision,
    }, { docId: context.docId, protectedRetry: false, skipSimulationPrepare: true })
    if (!isCurrent(context)) throw stale()
    if (!response) throw new Error(store.getState().lastError?.message || 'The pattern was not accepted.')
    if (response.design?.id !== context.designId || !Number.isSafeInteger(response.revision)
        || (context.revision != null && response.revision <= context.revision)) throw stale()
    // Patterns change topology. A design-only or lean delta response would make
    // the generic synchronizer fetch geometry from a later, unbound revision.
    if (!Array.isArray(response.nucleotides) || response.partial_geometry || response.geometry_skipped
        || response.diff_kind === 'cluster_only' || response.diff_kind === 'positions_only')
      throw new Error('The pattern response has no complete geometry. Refresh the part before continuing.')
    const adopted = await syncDesign(response)
    if (!adopted || !sameDocument(context) || store.getState().currentDesign !== response.design
        || currentRevision() !== response.revision) throw new Error('The pattern response was not accepted by the current part.')
    return response
  }
  return { capture, isCurrent,
    create(kind, body, context = capture()) {
      if (kind !== 'linear-pattern' && kind !== 'circular-pattern') throw new Error('Unsupported pattern kind.')
      return send(`/design/${kind}`, body, context)
    },
    edit(index, params, context, featureId) {
      if (!Number.isSafeInteger(index) || index < 0 || !featureId
          || context?.source?.feature_log?.[index]?.id !== featureId) return Promise.reject(new Error('The pattern feature changed. Reopen its editor.'))
      return send(`/design/features/${index}/edit`, { params, expected_feature_id: featureId }, context)
    },
  }
}
