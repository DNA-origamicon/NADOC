import { confirmedAssemblyRevision } from '../../api/assembly_response_authority.js'

/** Shared dialog policy; only target resolution and request transport vary. */
export function historyDialogHost({ store, api, source, assembly, instanceId, assemblySource, isTargetCurrent = () => true, getDocumentId }) {
  if (instanceId) {
    const parent = assemblySource ?? store.getState().currentAssembly
    const revision = confirmedAssemblyRevision(parent)
    const instance = parent?.instances?.find(item => item.id === instanceId)
    const design = instance?.source?.type === 'inline' ? instance.source.design : instance?.source?.revision
    if (!Number.isSafeInteger(revision) || !design || design.id !== source.id)
      throw new Error('Refresh the selected instance before changing its history.')
    const context = { docId: getDocumentId(), assemblyId: parent.id, revision, instanceId,
      designId: source.id, loadoutId: source.active_loadout_id ?? null,
      featureIds: source.feature_log.map(row => row.id) }
    return { context, transport: api.assemblyHistoryAPI, requiresTail: true,
      current: () => store.getState().assemblyActive && store.getState().currentAssembly === parent
        && getDocumentId() === context.docId && confirmedAssemblyRevision(parent) === revision
        && !store.getState().featureSeekPending && isTargetCurrent() }
  }
  if (assembly) {
    const revision = confirmedAssemblyRevision(source)
    if (!Number.isSafeInteger(revision)) throw new Error('Refresh the assembly before changing its history.')
    const context = { docId: getDocumentId(), assemblyId: source.id, revision,
      featureIds: source.feature_log.map(row => row.id) }
    return { context, transport: api.assemblyHistoryAPI, requiresTail: false,
      current: () => store.getState().assemblyActive && store.getState().currentAssembly === source
        && getDocumentId() === context.docId && confirmedAssemblyRevision(source) === revision
        && !store.getState().featureSeekPending }
  }
  const context = { docId: getDocumentId(), designId: source.id,
    loadoutId: source.active_loadout_id ?? null, revision: api.currentRevisionWatermark() }
  return { context, transport: api.partRepairAPI, requiresTail: false,
    current: () => store.getState().currentDesign === source && !store.getState().assemblyActive
      && getDocumentId() === context.docId && api.currentRevisionWatermark() === context.revision
      && !store.getState().featureSeekPending }
}
