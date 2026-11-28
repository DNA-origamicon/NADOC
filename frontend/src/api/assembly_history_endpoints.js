import { RepairRequestError } from './part_repair_endpoints.js'

/** Private job responses are applied only after a matching publication receipt. */
export function createAssemblyHistoryEndpoints({ request, apply }) {
  const base = '/assembly/features/evaluation/jobs'
  async function json(method, path, body, { context, signal } = {}) {
    let failure
    const result = await request(method, path, body, { docId: context.docId, signal,
      suppressBusy: true, protectedRetry: false, skipSimulationPrepare: true,
      onError: (status, detail) => { failure = new RepairRequestError(status, detail) } })
    if (failure) throw failure
    if (!result) throw new RepairRequestError(0, 'Assembly history request was cancelled or unavailable')
    return result
  }
  const path = id => `${base}/${encodeURIComponent(id)}`
  return {
    inputs(index, options) {
      const { context } = options
      const query = new URLSearchParams({ expected_revision: context.revision, expected_feature_id: context.featureIds[index] })
      return json('GET', `/assembly/features/${index}/inputs?${query}`, undefined, options)
    },
    dependencies: options => json('GET', options.context.instanceId
      ? `/assembly/instances/${encodeURIComponent(options.context.instanceId)}/features/dependencies`
      : '/assembly/features/dependencies', undefined, options),
    start(body, options) {
      const { context } = options
      const { index, ...inputs } = body
      const featureId = context.featureIds[index]
      if (!featureId) throw new RepairRequestError(409, 'The selected assembly feature no longer exists')
      if (context.instanceId) return json('POST', base, { operation: 'instance-history',
        expected_assembly_id: context.assemblyId, expected_revision: context.revision,
        instance_id: context.instanceId, instance_change: { operation: inputs.operation,
          design_id: context.designId, feature_id: featureId,
          ...(inputs.operation === 'edit' ? { params: inputs.inputs } : {}),
          ...(inputs.operation === 'suppress' ? { suppressed: inputs.suppressed } : {}),
          ...(inputs.operation === 'reorder' ? { destination: inputs.destination } : {}),
        } }, options)
      return json('POST', base, { ...inputs, expected_assembly_id: context.assemblyId,
        expected_revision: context.revision, feature_id: featureId }, options)
    },
    poll: (id, options) => json('GET', path(id), undefined, options),
    cancel: (id, options) => json('DELETE', path(id), undefined, options),
    commit: (id, options) => json('POST', `${path(id)}/commit`, undefined, options),
    async refreshCommitted(receipt, options) {
      const { context } = options
      if (receipt?.status !== 'committed' || !receipt.job_id || receipt.assembly_id !== context.assemblyId
          || !Number.isSafeInteger(receipt.revision) || receipt.revision !== context.revision + 1) {
        throw new RepairRequestError(409, 'The publication receipt belongs to another assembly or revision')
      }
      const result = await json('GET', '/assembly', undefined, options)
      if (result.assembly?.id !== context.assemblyId || result.revision !== receipt.revision) {
        throw new RepairRequestError(409, 'The published assembly changed. Refresh before continuing')
      }
      return result
    },
    apply,
  }
}
