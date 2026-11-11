/** Serialize writes so rapid +/- clicks cannot persist an older magnification last. */
export function createZoomVolumeAPI({ store, request, captureContext, designRevisions, assemblyRevisions, persistDesign, persistAssembly, signalDesignChanged }) {
  let tail = Promise.resolve()
  return (volumes, assembly = false) => {
    const key = assembly ? 'currentAssembly' : 'currentDesign'
    const id = store.getState()[key]?.id, context = captureContext()
    const body = { document_id: id, volumes: structuredClone(volumes) }
    const pending = tail.catch(() => {}).then(async () => {
      if (store.getState()[key]?.id !== id) return null
      const json = await request('PUT', `/${assembly ? 'assembly' : 'design'}/zoom-volumes`, body,
        { ...context, suppressBusy: true, skipSimulationPrepare: true })
      if (!json || store.getState()[key]?.id !== id) return null
      const tracker = assembly ? assemblyRevisions : designRevisions
      tracker.acceptMetadata(json, ['zoom_volumes'], id)
      if (assembly) persistAssembly()
      else { signalDesignChanged({ geometryUnchanged: true, metadataOnly: true }); persistDesign() }
      return json
    })
    tail = pending
    return pending
  }
}
