import { describe, expect, it, vi } from 'vitest'

const modulePath = './deformation_preview_endpoints.js'
const context = { docId: 'origin-doc', designId: 'part', revision: 7, loadoutId: null }
const origin = { preview_id: '11111111-1111-4111-8111-111111111111',
  expected_design_id: 'part', expected_revision: 7, feature_id: 'bend-feature' }
const receipt = { ...origin, status: 'applied', lease_id: '22222222-2222-4222-8222-222222222222',
  doc_id: context.docId, deformation_id: 'operation', request_sequence: 3, design_id: 'part', revision: 8 }

async function make(request) {
  return (await import(modulePath)).createDeformationPreviewEndpoints({ request })
}

describe('private deformation preview transport', () => {
  it('uses only the dedicated guarded POST paths without canonical sync or protected retry', async () => {
    const request = vi.fn(async () => ({})), api = await make(request)
    const abort = new AbortController(), options = { context, signal: abort.signal }
    await api.prepare(origin, options)
    await api.evaluate({ ...origin, lease_id: receipt.lease_id, request_sequence: 1, params: {} }, options)
    await api.apply({ ...origin, lease_id: receipt.lease_id, request_sequence: 2, params: {} }, options)
    await api.cancel(origin, options)
    await api.status({ ...origin, lease_id: receipt.lease_id }, options)
    expect(request.mock.calls.map(([method, path]) => [method, path])).toEqual([
      ['POST', '/design/features/deformation-preview'],
      ...['evaluate', 'apply', 'cancel', 'status'].map(action => ['POST', `/design/features/deformation-preview/${action}`]),
    ])
    for (const [, , , opts] of request.mock.calls) expect(opts).toMatchObject({
      docId: context.docId, signal: abort.signal, suppressBusy: true,
      protectedRetry: false, skipSimulationPrepare: true,
    })
  })

  it('requires an explicit context before issuing even a cancellation request', async () => {
    const request = vi.fn(), api = await make(request)
    await expect(api.cancel(origin)).rejects.toThrow(/context/i)
    expect(request).not.toHaveBeenCalled()
  })

  it('preserves typed errors and treats unavailable responses as uncertain transport failure', async () => {
    const detail = { code: 'preview_busy', detail: 'Another preview is running.' }
    const api = await make(async (_method, _path, _body, options) => {
      options.onError(429, detail); return null
    })
    await expect(api.prepare(origin, { context })).rejects.toMatchObject({ status: 429, code: 'preview_busy', detail,
      message: 'Another preview is running.' })
    const unavailable = await make(async () => null)
    await expect(unavailable.apply(origin, { context })).rejects.toMatchObject({ status: 0 })
  })

  it('refreshes published data privately between two exact session-bound status checks', async () => {
    const source = { design: { id: 'part', active_loadout_id: null }, revision: 8, validation: { passed: true } }
    const geometry = { nucleotides: [], helix_axes: [], design: { id: 'hostile-overwrite' }, revision: 999 }
    const responses = [receipt, source, geometry,
      { doc_id: context.docId, design_id: 'part', revision: 8, has_design: true }, receipt]
    const request = vi.fn(async () => responses.shift()), api = await make(request)
    const result = await api.refreshCommitted(receipt, { context })
    expect(result).toEqual({ ...source, nucleotides: [], helix_axes: [] })
    expect(request.mock.calls.map(([, path]) => path)).toEqual([
      '/design/features/deformation-preview/status', '/design', '/design/geometry',
      '/design/revision', '/design/features/deformation-preview/status',
    ])
    expect(request.mock.calls[0][2]).toEqual({ ...origin, lease_id: receipt.lease_id })
    expect(request.mock.calls[4][2]).toEqual(request.mock.calls[0][2])
  })

  it.each(['initial_status', 'design', 'geometry', 'revision', 'final_status'])('refuses stale or incomplete %s without adopting display', async stage => {
    const status = { ...receipt }, source = { design: { id: 'part', active_loadout_id: null }, revision: 8 }
    const geometry = { nucleotides: [], helix_axes: [] }
    const revision = { doc_id: context.docId, design_id: 'part', revision: 8, has_design: true }
    const responses = [status, source, geometry, revision, { ...receipt }]
    if (stage === 'initial_status') responses[0].lease_id = 'foreign'
    if (stage === 'design') source.revision = 9
    if (stage === 'geometry') geometry.partial_geometry = true
    if (stage === 'revision') revision.doc_id = 'other'
    if (stage === 'final_status') responses[4].request_sequence++
    const api = await make(async () => responses.shift())
    await expect(api.refreshCommitted(receipt, { context })).rejects.toMatchObject({ status: expect.any(Number) })
  })

  it('refuses a foreign publication receipt before any reads', async () => {
    const request = vi.fn(), api = await make(request)
    await expect(api.refreshCommitted({ ...receipt, revision: 7 }, { context })).rejects.toMatchObject({ status: 409 })
    expect(request).not.toHaveBeenCalled()
  })
})

it('prepares creation only through the dedicated source-bound endpoint', async () => {
  const request = vi.fn(async () => ({})), api = await make(request)
  const body = { ...origin, mode: 'create', type: 'twist', targets: null, cluster_ids: ['placement'] }
  await api.prepareCreation(body, { context })
  expect(request).toHaveBeenCalledWith('POST', '/design/features/deformation-preview/create', body,
    expect.objectContaining({ docId: 'origin-doc', protectedRetry: false, skipSimulationPrepare: true }))
})
