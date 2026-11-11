/** Apply only animation metadata; never replace live trajectory or assembly geometry. */
export function createKeyframeDeletionAPI({ store, request, designRevisions, assemblyRevisions, persistDesign, persistAssembly, signalDesignChanged }) {
  return async function deleteKeyframe(assembly, animationId, keyframeId) {
    const host = assembly ? 'assembly' : 'design', key = assembly ? 'currentAssembly' : 'currentDesign'
    const id = store.getState()[key]?.id
    const json = await request('DELETE', `/${host}/animations/${animationId}/keyframes/${keyframeId}?metadata_only=true`, undefined,
      { suppressBusy: true, skipSimulationPrepare: true })
    if (!json) return null
    const current = store.getState()[key]
    if (current?.id !== id || json[host]?.id !== id) return json
    const tracker = assembly ? assemblyRevisions : designRevisions
    if (!tracker.acceptMetadata(assembly ? { design: json.assembly, revision: json.revision } : json, ['animations'], id)) return json
    store.setState({ [key]: { ...current, animations: json[host].animations } })
    if (assembly) persistAssembly()
    else { signalDesignChanged({ geometryUnchanged: true, metadataOnly: true }); persistDesign() }
    return json
  }
}
