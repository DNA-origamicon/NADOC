import { describe, expect, it, vi } from 'vitest'
import { createPartRepairEndpoints } from './part_repair_endpoints.js'
import { comparisonContext, comparisonEnvelope } from '../test-helpers/part_comparison.js'

describe('explicit comparison read', () => {
  it('sends only current guards to the original document with no metadata or geometry publication', async () => {
    const request = vi.fn(async () => comparisonEnvelope()), acknowledge = vi.fn(), apply = vi.fn()
    const api = createPartRepairEndpoints({ request, acknowledge, apply }), abort = new AbortController()
    const body = { projection_version: 1, expected_design_id: 'part', expected_revision: 4,
      expected_draft_id: 'draft', expected_generation: 3 }
    const result = await api.compare('job/id', body, { context: comparisonContext(), signal: abort.signal })
    expect(request).toHaveBeenCalledExactlyOnceWith('POST', '/design/features/evaluation/jobs/job%2Fid/comparison', body,
      expect.objectContaining({ docId: 'origin', signal: abort.signal, protectedRetry: false,
        suppressBusy: true, skipSimulationPrepare: true }))
    expect(result.status).toBe('projected')
    expect(acknowledge).not.toHaveBeenCalled(); expect(apply).not.toHaveBeenCalled()
  })

  it('retains unsupported-scope diagnostics for an explicit unavailable view', async () => {
    const detail = { code: 'unsupported_comparison_scope', detail: 'Comparison does not yet cover helices' }
    const request = vi.fn(async (_method, _path, _body, options) => { options.onError(422, detail); return null })
    const api = createPartRepairEndpoints({ request })
    await expect(api.compare('job', {}, { context: comparisonContext() })).rejects.toMatchObject({ status: 422, detail })
    expect(request).toHaveBeenCalledOnce()
  })
})
