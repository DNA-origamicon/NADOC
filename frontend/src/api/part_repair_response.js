/** Draft/source responses acknowledge metadata without replacing or cloning geometry. */
export function createPartRepairResponse({ store, revisions, getDocId, syncDesign }) {
  function matches(context) {
    const design = store.getState().currentDesign
    return context?.docId === getDocId() && context.designId === design?.id
      && context.loadoutId === (design?.active_loadout_id ?? null)
      && context.revision === revisions.current()
  }
  function summaryPatch(json) {
    if (!json?.design || typeof json.design.id !== 'string' || !json.design.id) return {}
    const old = store.getState().repairMetadata
    if (old?.designId === json.design.id && old.revision > json.revision) return {}
    if (!Object.hasOwn(json, 'repair_draft')) {
      return old?.designId === json.design.id ? {} : { repairMetadata: null }
    }
    return { repairMetadata: { designId: json.design.id, revision: json.revision,
      summary: json.repair_draft ?? null } }
  }
  return {
    summaryPatch,
    acknowledge(json, context) {
      if (!matches(context) || json?.design_id !== context.designId || !Number.isSafeInteger(json.revision)
          || json.revision < context.revision || !revisions.acceptMetadata(json, [], context.designId)) return false
      store.setState({ repairMetadata: { designId: json.design_id, revision: json.revision,
        summary: json.repair_draft ?? null } })
      return true
    },
    apply(json, context) {
      if (!matches(context) || json?.design?.id !== context.designId) throw new Error('The evaluated result belongs to an older document state')
      return syncDesign(json)
    },
  }
}
