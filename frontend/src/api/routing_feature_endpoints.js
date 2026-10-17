import { createSourceBoundRequests } from './source_bound_requests.js'

/** Pre-child references and publication share one captured part/revision. */
export function createRoutingFeatureAPI(deps) {
  const bound = createSourceBoundRequests({ ...deps, label: 'Fine Routing' })
  const stale = () => new Error('The routing child or part changed. Reopen its editor.')
  function selected(index, subIndex, context, featureId, childId) {
    const parent = context?.source?.feature_log?.[index], child = parent?.children?.[subIndex]
    if (!Number.isSafeInteger(index) || index < 0 || !Number.isSafeInteger(subIndex) || subIndex < 0
        || !bound.isCurrent(context) || !context.designId || !Number.isSafeInteger(context.revision) || context.revision < 0
        || parent?.feature_type !== 'routing-cluster' || parent.id !== featureId
        || child?.feature_type !== 'minor' || child.id !== childId || !featureId || !childId) throw stale()
    return child
  }
  return {
    capture: bound.capture, isCurrent: bound.isCurrent,
    async load(index, subIndex, context, featureId, childId) {
      const child = selected(index, subIndex, context, featureId, childId)
      const query = new URLSearchParams({ sub_index: subIndex, expected_design_id: context.designId,
        expected_revision: context.revision, expected_feature_id: featureId, expected_child_id: childId })
      const result = await deps.request('GET', `/design/features/${index}/routing-inputs?${query}`, undefined,
        { docId: context.docId, protectedRetry: false, skipSimulationPrepare: true })
      selected(index, subIndex, context, featureId, childId)
      if (!result) throw new Error(deps.store.getState().lastError?.message || 'Routing inputs could not be loaded.')
      if (result.source_design_id !== context.designId || result.source_revision !== context.revision
          || result.feature_id !== featureId || result.child_id !== childId || result.kind !== child.op_subtype
          || !result.params || typeof result.params !== 'object' || Array.isArray(result.params)
          || !result.prefix || !['helices', 'strands', 'crossovers', 'forced_ligations'].every(key => Array.isArray(result.prefix[key]))) throw stale()
      // Server emits only bounded scalar reference inventories; never adopt
      // this pre-child design into the live store or fetch its geometry.
      let rows = 0
      for (const key of ['helices', 'strands', 'crossovers', 'forced_ligations']) {
        const entries = result.prefix[key]
        rows += entries.length
        if (rows > 30_000) throw new Error('The routing reference inventory exceeds its limit.')
        for (const entry of entries) {
          if (!entry || typeof entry.id !== 'string' || !entry.id) throw new Error('Invalid routing reference inventory.')
          if (key === 'strands') {
            if (!Array.isArray(entry.domains)) throw new Error('Invalid routing strand inventory.')
            rows += entry.domains.length
            if (rows > 30_000) throw new Error('The routing reference inventory exceeds its limit.')
          }
        }
      }
      return result
    },
    async edit(index, subIndex, params, context, featureId, childId) {
      selected(index, subIndex, context, featureId, childId)
      return bound.send(`/design/features/${index}/edit?sub_index=${subIndex}`,
        { params, expected_feature_id: featureId, expected_child_id: childId }, context)
    },
  }
}
