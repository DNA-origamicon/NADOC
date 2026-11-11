/** Checkpoint publication updates history without replacing live geometry. */
export function createPresentationCheckpointAPI({ store, request, designRevisions, assemblyRevisions, persistDesign, persistAssembly }) {
  return async function savePresentationCheckpoint(kind, { assembly = false, documentId } = {}) {
    const key = assembly ? 'currentAssembly' : 'currentDesign'
    const current = store.getState()[key]
    const id = documentId ?? current?.id
    if (!id || current?.id !== id) throw new Error('The active document changed')
    const json = await request('POST', `/${assembly ? 'assembly' : 'design'}/features/presentation-state`,
      { document_id: id, kind }, { skipSimulationPrepare: true })
    if (!json) throw new Error(store.getState().lastError?.message || 'Could not save presentation state')
    if (store.getState()[key]?.id !== id) return json
    const tracker = assembly ? assemblyRevisions : designRevisions
    if (tracker.acceptMetadata(json, ['feature_log'], id)) {
      store.setState({ [key]: { ...store.getState()[key], feature_log: json.feature_log } })
      if (assembly) persistAssembly()
      else persistDesign()
    }
    return json
  }
}
