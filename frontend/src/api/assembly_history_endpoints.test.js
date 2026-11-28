import { expect, it, vi } from 'vitest'
import { createAssemblyHistoryEndpoints } from './assembly_history_endpoints.js'

const context = { docId: 'doc', assemblyId: 'assembly', revision: 7, featureIds: ['first', 'second'] }
it.each([
  [{ operation: 'edit', inputs: { length_bp: 10 } }, { params: { length_bp: 10 } }],
  [{ operation: 'suppress', suppressed: true }, { suppressed: true }],
  [{ operation: 'reorder', destination: 0 }, { destination: 0 }],
  [{ operation: 'delete' }, {}],
])('binds selected-instance changes to the assembly revision: %j', async (change, fields) => {
  const request = vi.fn(async () => ({ job_id: 'job' }))
  const api = createAssemblyHistoryEndpoints({ request })
  await api.start({ ...change, index: 1 }, { context: { ...context, instanceId: 'instance', designId: 'part' } })
  expect(request).toHaveBeenCalledWith('POST', '/assembly/features/evaluation/jobs', {
    operation: 'instance-history', expected_assembly_id: 'assembly', expected_revision: 7,
    instance_id: 'instance', instance_change: { operation: change.operation,
      design_id: 'part', feature_id: 'second', ...fields },
  }, expect.objectContaining({ docId: 'doc' }))
})
it('binds the selected row to its captured identity and owns private requests', async () => {
  const request = vi.fn(async () => ({ job_id: 'job' })), apply = vi.fn()
  const api = createAssemblyHistoryEndpoints({ request, apply })
  await api.start({ operation: 'suppress', suppressed: true, index: 1 }, { context })
  expect(request).toHaveBeenCalledWith('POST', '/assembly/features/evaluation/jobs', {
    operation: 'suppress', suppressed: true, expected_assembly_id: 'assembly', expected_revision: 7, feature_id: 'second',
  }, expect.objectContaining({ docId: 'doc', suppressBusy: true }))
  expect(apply).not.toHaveBeenCalled()
})
it('refreshes a matching commit privately and refuses a newer result', async () => {
  const request = vi.fn(async () => ({ assembly: { id: 'assembly' }, revision: 8 })), apply = vi.fn()
  const api = createAssemblyHistoryEndpoints({ request, apply })
  const receipt = { job_id: 'job', status: 'committed', assembly_id: 'assembly', revision: 8 }
  expect(await api.refreshCommitted(receipt, { context })).toMatchObject({ revision: 8 })
  expect(apply).not.toHaveBeenCalled()
  await expect(api.refreshCommitted({ ...receipt, assembly_id: 'other' }, { context })).rejects.toThrow('another assembly')
  request.mockResolvedValue({ assembly: { id: 'assembly' }, revision: 9 })
  await expect(api.refreshCommitted(receipt, { context })).rejects.toThrow('changed')
})
it('propagates job errors and missing selections without publishing', async () => {
  const request = vi.fn(async (_m, _p, _b, options) => { options.onError(409, 'Source changed'); return null })
  const api = createAssemblyHistoryEndpoints({ request })
  await expect(api.poll('job', { context })).rejects.toThrow('Source changed')
  expect(() => api.start({ index: 9 }, { context })).toThrow('no longer exists')
})
