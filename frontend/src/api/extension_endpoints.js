/** Closed terminal CRUD: the original document owns both the edit and its reply. */
export function createExtensionEndpoints({ getDesign, getRevision, getDocId, documentRequests,
  request, syncDesign, reportError = () => {}, getError = () => null,
  isAssembly = () => false, geometry = true }) {
  let epoch = 0
  const captureExtensionContext = () => Object.freeze({ source: getDesign(), revision: getRevision(),
    docId: getDocId(), generation: documentRequests.capture(), epoch })
  const sameDocument = context => context && context.epoch === epoch
    && documentRequests.isCurrent(context.generation) && getDocId() === context.docId
    && getDesign()?.id === context.source?.id && !isAssembly()
  const current = context => sameDocument(context) && getDesign() === context.source
    && getRevision() === context.revision
  const fail = (context, message) => {
    if (sameDocument(context)) reportError(message)
    return null
  }
  const message = () => {
    const value = getError()?.message
    return typeof value === 'string' ? value : value?.message
      || 'The extension edit was not confirmed. Refresh the part before retrying.'
  }
  function completeGeometry(response, deletedIds) {
    if (!geometry) return true // The 2D host explicitly requests topology only.
    if (response.geometry_skipped || response.diff_kind === 'cluster_only' || response.diff_kind === 'positions_only') return false
    if (!response.partial_geometry) return Array.isArray(response.helix_axes)
      && (Array.isArray(response.nucleotides) || !!response.nucleotides_compact)
    // Existing fast deletion removes only these synthetic records. Its merge is
    // valid only against the exact captured source, checked before synchronization.
    if (!Array.isArray(deletedIds) || !Array.isArray(response.nucleotides) || response.nucleotides.length
        || !Array.isArray(response.changed_helix_ids)
        || (response.helix_axes != null && (!Array.isArray(response.helix_axes) || response.helix_axes.length))) return false
    const expected = new Set(deletedIds.map(id => `__ext_${id}`))
    return response.changed_helix_ids.length === expected.size
      && new Set(response.changed_helix_ids).size === expected.size
      && response.changed_helix_ids.every(id => expected.has(id))
  }
  function completeTopology(design) {
    // The topology-only editor still needs a complete design-bearing reply.
    // This is an envelope check, not a second model validator or a deep clone.
    return design && typeof design === 'object' && !Array.isArray(design)
      && ['helices', 'strands', 'extensions', 'feature_log'].every(key => Array.isArray(design[key]))
  }
  async function send(method, path, body, context, { deletedIds, empty = false } = {}) {
    context ??= captureExtensionContext()
    if (!current(context) || !context.source?.id)
      return fail(context, 'The part changed. Reopen the extension dialog on the current part.')
    if (!Number.isSafeInteger(context.revision) || context.revision < 0)
      return fail(context, 'Refresh the current part before editing extensions.')
    let response
    try {
      response = await request(method, path, { ...body, expected_revision: context.revision },
        { docId: context.docId, protectedRetry: false, skipSimulationPrepare: true })
    } catch (error) { return fail(context, error?.message || 'The extension request failed.') }
    if (!current(context)) return fail(context, 'The part changed while the extension edit was pending. Refresh before retrying.')
    if (!response) return fail(context, message())
    if (response.design?.id !== context.source.id || !Number.isSafeInteger(response.revision)
        || response.revision < context.revision
        || (Object.hasOwn(response, 'no_op') && typeof response.no_op !== 'boolean')
        || (response.revision === context.revision && response.no_op !== true)
        || (response.no_op === true && response.revision !== context.revision))
      return fail(context, 'The extension response is no longer current. Your current part was kept.')
    if (!completeTopology(response.design))
      return fail(context, 'The extension response has no complete topology. Refresh before continuing.')
    if (!completeGeometry(response, deletedIds))
      return fail(context, 'The extension response has no complete matching geometry. Refresh before continuing.')
    try {
      // The generic partial merger treats an empty changed list as a full
      // replacement. An acknowledged empty delete owns no geometry at all.
      if (empty && response.partial_geometry && response.changed_helix_ids.length === 0)
        await syncDesign(response, { skipGeometry: true })
      else await syncDesign(response)
    }
    catch (error) { return fail(context, error?.message || 'The extension edit could not be displayed.') }
    // Shared sync returns older packets even when it declines to adopt them.
    if (!sameDocument(context) || getDesign() !== response.design || getRevision() !== response.revision) return null
    return response
  }
  return {
    captureExtensionContext,
    invalidate() { epoch++ }, // Backend restart must retire even same-ID/revision contexts.
    createStrandExtension(strandId, end, opts = {}, context) {
      return send('POST', '/design/extensions', { ...opts, strand_id: strandId, end }, context)
    },
    updateStrandExtension(id, opts, context) {
      return send('PUT', `/design/extensions/${encodeURIComponent(id)}`, opts, context)
    },
    deleteStrandExtension(id, context) {
      return send('DELETE', `/design/extensions/${encodeURIComponent(id)}`, {}, context, { deletedIds: [id] })
    },
    upsertStrandExtensionsBatch(items, context) {
      // Batch is complete replacement, unlike PUT: omitted values clear fields.
      // Preserve ordering/duplicates so the server validates every input first.
      return send('POST', '/design/extensions/batch', { items: items.map(item => ({
        strand_id: item.strandId, end: item.end, sequence: item.sequence ?? null,
        modification: item.modification ?? null, label: item.label ?? null,
      })) }, context, { empty: items.length === 0 })
    },
    deleteStrandExtensionsBatch(ids, context) {
      return send('DELETE', '/design/extensions/batch', { ext_ids: [...ids] }, context,
        { deletedIds: ids, empty: ids.length === 0 })
    },
  }
}
