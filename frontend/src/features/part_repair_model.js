/** Input-only repair state. No geometry, persistence, or readiness inferred from a draft. */
export const REPAIR_LIMITS = Object.freeze({ actions: 64, nodes: 10000, bytes: 256000, depth: 64, path: 16 })

export function cloneRepairInput(value) {
  let nodes = 0, size = 0
  function copy(item, depth) {
    if (++nodes > REPAIR_LIMITS.nodes || depth > REPAIR_LIMITS.depth) throw new Error('Repair input is too complex')
    size += 16
    if (typeof item === 'string') size += item.length * 4
    if (size > REPAIR_LIMITS.bytes) throw new Error('Repair input exceeds its size limit')
    if (item === null || typeof item === 'boolean' || typeof item === 'string') return item
    if (typeof item === 'number' && Number.isFinite(item)) return item
    if (Array.isArray(item)) {
      if (item.length + nodes > REPAIR_LIMITS.nodes) throw new Error('Repair input is too complex')
      return item.map(child => copy(child, depth + 1))
    }
    if (item && Object.getPrototypeOf(item) === Object.prototype) {
      const entries = Object.entries(item)
      if (entries.length + nodes > REPAIR_LIMITS.nodes) throw new Error('Repair input is too complex')
      return Object.fromEntries(entries.map(([key, child]) => {
        size += key.length * 4
        return [key, copy(child, depth + 1)]
      }))
    }
    throw new Error('Repair inputs must be finite JSON values')
  }
  return copy(value, 0)
}

export function sameRepairContext(a, b) {
  if (a == null || b == null) return a === b
  return !!a && !!b && ['docId', 'designId', 'loadoutId', 'revision', 'editable', 'cursor', 'subCursor']
    .every(key => a[key] === b[key])
}

export function repairGuards(context, draft = null) {
  if (!context?.designId || !Number.isSafeInteger(context.revision) || context.revision < 0) {
    throw new Error('Load the current part revision before repairing')
  }
  return { draft_version: 1, expected_design_id: context.designId, expected_revision: context.revision,
    expected_draft_id: draft?.draft_id ?? null, expected_generation: draft?.generation ?? null }
}

export function resolveRepairFeature(design, featureId, childId = null) {
  const found = []
  for (const [index, entry] of (design?.feature_log ?? []).entries()) {
    if (entry.id === featureId && childId == null && entry.feature_type !== 'routing-cluster') {
      found.push({ entry, index, featureId, childId: null, subIndex: null })
    }
    if (entry.feature_type === 'routing-cluster') {
      for (const [subIndex, child] of (entry.children ?? []).entries()) {
        if ((entry.id === featureId && child.id === childId) || (childId == null && child.id === featureId)) {
          found.push({ entry: child, index, subIndex, featureId: entry.id, childId: child.id })
        }
      }
    }
  }
  if (found.length !== 1) throw new Error(found.length ? 'Feature identity is ambiguous' : 'The feature is no longer present')
  return found[0]
}

export function repairActions(actions) {
  if (!Array.isArray(actions) || !actions.length || actions.length > REPAIR_LIMITS.actions) {
    throw new Error('A proposal needs between 1 and 64 input changes')
  }
  return cloneRepairInput(actions)
}

export function numericalRepairReviewRequired(draft) {
  return (draft?.actions ?? []).some(action => action.action === 'upgrade_numerical_contract')
}

export function repairIssues(value) {
  const detail = value?.detail ?? value
  const issues = detail?.issues ?? detail?.assessment?.issues ?? (detail?.code ? [detail] : [])
  return issues.map(issue => ({ ...issue,
    parameter_path: issue.parameter_path ?? issue.references?.[0]?.parameter_path ?? null }))
}

export function repairJobView(job, context, draft) {
  if (!job || !sameRepairContext(job.context, context)) return { ready: false, selection: null, result: null }
  const response = job.response, result = response?.result
  const current = !response?.stale && !response?.source_busy && response?.status === 'complete'
  const draftMatches = job.operation === 'repair' && draft?.draft_id === job.draftId && draft?.generation === job.generation
  return { result, ready: current && draftMatches && result?.status === 'ready',
    selection: current && job.operation === 'selection' && result?.status === 'preview'
      && !result.selection?.candidates_invalidated ? result.selection : null }
}

export function repairPublishedStatus(job, context) {
  if (!job || job.operation !== 'verify' || !sameRepairContext(job.context, context)) return 'unchecked'
  const { response } = job
  if (response?.stale || response?.source_busy) return 'stale'
  if (response?.status !== 'complete') return 'checking'
  return ['verified', 'reproduced_import'].includes(response.result?.status) ? response.result.status : 'failed'
}
