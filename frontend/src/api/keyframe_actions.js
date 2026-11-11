/** Merge presentation metadata without replacing the live molecular display. */
export function createKeyframeActionsAPI({ store, request, designRevisions, assemblyRevisions, persistDesign, persistAssembly, signalDesignChanged }) {
  return async (assembly, action, animationId, keyframeId, body = {}) => {
    const key = assembly ? 'currentAssembly' : 'currentDesign', host = assembly ? 'assembly' : 'design'
    const id = store.getState()[key]?.id
    const json = await request('POST', `/${host}/animations/${animationId}/keyframes/${keyframeId}/${action}`, body,
      { suppressBusy: true, skipSimulationPrepare: true })
    if (!json) return null
    const current = store.getState()[key], metadata = json[host]
    if (current?.id !== id || metadata?.id !== id) return null
    const fields = assembly ? ['animations', 'camera_poses', 'configurations'] : ['animations', 'camera_poses']
    if (!(assembly ? assemblyRevisions : designRevisions).acceptMetadata({ design: metadata, revision: json.revision }, fields, id)) return null
    store.setState({ [key]: { ...current, ...metadata } })
    if (assembly) persistAssembly()
    else { signalDesignChanged({ geometryUnchanged: true, metadataOnly: true }); persistDesign() }
    return json
  }
}
