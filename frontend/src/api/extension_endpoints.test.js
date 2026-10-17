import { describe, expect, it, vi } from 'vitest'
import { createExtensionEndpoints } from './extension_endpoints.js'

const model = () => ({ id: 'part', helices: [], strands: [], extensions: [], feature_log: [] })

function fixture({ geometry = true } = {}) {
  let design = model(), revision = 4, doc = 'doc', generation = 0
  const request = vi.fn(async () => ({ design: model(), revision: 5,
    validation: {}, nucleotides: [], helix_axes: [] }))
  const syncDesign = vi.fn(async response => { design = response.design; revision = response.revision; return response })
  const reportError = vi.fn()
  const api = createExtensionEndpoints({ getDesign: () => design, getRevision: () => revision,
    getDocId: () => doc, documentRequests: { capture: () => generation, isCurrent: token => token === generation },
    request, syncDesign, reportError, geometry })
  return { api, request, syncDesign, reportError, current: () => design, change(kind) {
    if (kind === 'reset') generation++
    if (kind === 'document') doc = 'other'
    if (kind === 'revision') revision++
    if (kind === 'source') design = { ...design }
  } }
}

describe('source-bound terminal extension CRUD', () => {
  it.each([
    ['createStrandExtension', ['strand', 'five_prime', { sequence: 'AT', modification: null }], 'POST', '/design/extensions', { strand_id: 'strand', end: 'five_prime', sequence: 'AT', modification: null }],
    ['updateStrandExtension', ['ext/a', { sequence: '', label: '' }], 'PUT', '/design/extensions/ext%2Fa', { sequence: '', label: '' }],
    ['deleteStrandExtension', ['ext/a'], 'DELETE', '/design/extensions/ext%2Fa', {}],
    ['upsertStrandExtensionsBatch', [[{ strandId: 's', end: 'three_prime', sequence: 'AT' }, { strandId: 's', end: 'three_prime', modification: 'cy3' }]], 'POST', '/design/extensions/batch', { items: [
      { strand_id: 's', end: 'three_prime', sequence: 'AT', modification: null, label: null },
      { strand_id: 's', end: 'three_prime', sequence: null, modification: 'cy3', label: null },
    ] }],
    ['deleteStrandExtensionsBatch', [['e', 'e']], 'DELETE', '/design/extensions/batch', { ext_ids: ['e', 'e'] }],
  ])('%s dispatches once with the source revision and adopts exact candidate geometry', async (method, args, verb, path, body) => {
    const f = fixture(), result = await f.api[method](...args)
    expect(f.request).toHaveBeenCalledExactlyOnceWith(verb, path, { ...body, expected_revision: 4 },
      { docId: 'doc', protectedRetry: false, skipSimulationPrepare: true })
    expect(f.syncDesign).toHaveBeenCalledExactlyOnceWith(result)
    expect(f.current()).toBe(result.design)
  })
  it('preserves single-update null/omission and does not coalesce invalid earlier batch duplicates', async () => {
    const f = fixture()
    await f.api.updateStrandExtension('e', { sequence: null })
    expect(f.request.mock.calls[0][2]).toEqual({ sequence: null, expected_revision: 4 })
    await f.api.upsertStrandExtensionsBatch([{ strandId: 's', end: 'five_prime', sequence: 'AX' },
      { strandId: 's', end: 'five_prime', sequence: 'AT' }])
    expect(f.request.mock.calls[1][2].items.map(item => item.sequence)).toEqual(['AX', 'AT'])
  })
  it.each(['reset', 'document', 'revision', 'source'])('refuses a dialog captured before %s without dispatch', async kind => {
    const f = fixture(), context = f.api.captureExtensionContext(); f.change(kind)
    expect(await f.api.upsertStrandExtensionsBatch([{ strandId: 's', end: 'five_prime', sequence: 'AT' }], context)).toBeNull()
    expect(f.request).not.toHaveBeenCalled()
  })
  it.each(['reset', 'document', 'revision', 'source'])('does not adopt a held result after %s', async kind => {
    const f = fixture(); let finish
    f.request.mockReturnValue(new Promise(resolve => { finish = resolve }))
    const result = f.api.deleteStrandExtension('e'); f.change(kind)
    finish({ design: model(), revision: 5, nucleotides: [], helix_axes: [] })
    expect(await result).toBeNull(); expect(f.syncDesign).not.toHaveBeenCalled()
  })
  it.each([null, { design: { id: 'other' }, revision: 5, nucleotides: [] },
    { design: model(), revision: 3, nucleotides: [] },
    { design: model(), revision: 5 },
    { design: model(), revision: 5, nucleotides: [], partial_geometry: true, changed_helix_ids: ['__ext_e'] },
  ])('rejects absent, foreign, stale or incomplete upsert response without later geometry reads', async response => {
    const f = fixture(); f.request.mockResolvedValue(response)
    expect(await f.api.updateStrandExtension('e', { sequence: 'AT' })).toBeNull()
    expect(f.syncDesign).not.toHaveBeenCalled(); expect(f.request).toHaveBeenCalledTimes(1)
  })
  it('acknowledges the existing synthetic-only delete response against its exact source', async () => {
    const f = fixture(); f.request.mockResolvedValue({ design: model(), revision: 5,
      nucleotides: [], partial_geometry: true, changed_helix_ids: ['__ext_e'] })
    expect(await f.api.deleteStrandExtensionsBatch(['e', 'e'])).not.toBeNull()
    expect(f.syncDesign).toHaveBeenCalledTimes(1)
  })
  it('does not accept a partial deletion covering unrelated geometry', async () => {
    const f = fixture(); f.request.mockResolvedValue({ design: model(), revision: 5,
      nucleotides: [], partial_geometry: true, changed_helix_ids: ['h'] })
    expect(await f.api.deleteStrandExtension('e')).toBeNull(); expect(f.syncDesign).not.toHaveBeenCalled()
  })
  it('does not return an accepted receipt when shared sync skips or replaces its candidate', async () => {
    const f = fixture(); f.syncDesign.mockImplementation(async response => response)
    expect(await f.api.deleteStrandExtension('e')).toBeNull()
  })
  it('accepts topology-only 2D results through the same source binding', async () => {
    const f = fixture({ geometry: false }); f.request.mockResolvedValue({ design: model(), revision: 5 })
    expect(await f.api.updateStrandExtension('e', { label: '' })).not.toBeNull()
  })
  it('keeps empty batch no-op semantics with an unchanged acknowledged revision', async () => {
    const f = fixture(); f.request.mockResolvedValue({ design: model(), revision: 4, no_op: true, nucleotides: [], helix_axes: [] })
    expect(await f.api.upsertStrandExtensionsBatch([])).not.toBeNull()
    expect(f.request.mock.calls[0][2]).toEqual({ items: [], expected_revision: 4 })
    f.request.mockResolvedValue({ design: model(), revision: 4, no_op: true, nucleotides: [],
      partial_geometry: true, changed_helix_ids: [] })
    expect(await f.api.deleteStrandExtensionsBatch([])).not.toBeNull()
  })
  it('invalidates a captured dialog on a session restart even when the source and revision repeat', async () => {
    const f = fixture(), context = f.api.captureExtensionContext()
    f.api.invalidate()
    expect(await f.api.deleteStrandExtension('e', context)).toBeNull()
    expect(f.request).not.toHaveBeenCalled()
  })
  it('returns null and reports a refused or failed request without retrying it', async () => {
    const f = fixture(); f.request.mockRejectedValue(new Error('refused'))
    expect(await f.api.deleteStrandExtension('e')).toBeNull()
    expect(f.reportError).toHaveBeenCalledWith('refused'); expect(f.request).toHaveBeenCalledTimes(1)
  })
})
