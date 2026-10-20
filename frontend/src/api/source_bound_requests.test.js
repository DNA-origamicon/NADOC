import { expect, it, vi } from 'vitest'
import { createSourceBoundRequests } from './source_bound_requests.js'

function fixture() {
  let state = { currentDesign: { id: 'part', feature_log: [{ id: 'feature' }] }, assemblyActive: false }
  let revision = 4, generation = 0, doc = 'doc'
  const request = vi.fn(async () => ({ design: { id: 'part' }, revision: 5, nucleotides: [] }))
  const syncDesign = vi.fn(async value => { state = { ...state, currentDesign: value.design }; revision = value.revision; return value })
  const api = createSourceBoundRequests({ store: { getState: () => state }, request, syncDesign, label: 'extrusion',
    getDocId: () => doc, currentRevision: () => revision,
    documentRequests: { capture: () => generation, isCurrent: token => token === generation } })
  return { api, request, syncDesign, change: kind => {
    if (kind === 'reset') generation++
    if (kind === 'revision') revision++
    if (kind === 'document') doc = 'other'
    if (kind === 'source') state = { ...state, currentDesign: { ...state.currentDesign } }
  } }
}
it('sends exact original source and stable feature identity once and adopts complete geometry', async () => {
  const f = fixture(), context = f.api.capture(), params = { length_bp: -7, history_seed: 'unchanged' }
  await f.api.edit(0, params, context, 'feature')
  expect(f.request).toHaveBeenCalledWith('POST', '/design/features/0/edit', { params, expected_design_id: 'part', expected_revision: 4, expected_feature_id: 'feature' }, { docId: 'doc', protectedRetry: false, skipSimulationPrepare: true, onError: expect.any(Function) })
  expect(f.syncDesign).toHaveBeenCalledTimes(1)
})
it.each(['reset', 'revision', 'document', 'source'])('does not publish a held response after %s', async kind => {
  const f = fixture(), context = f.api.capture(); let finish
  f.request.mockReturnValue(new Promise(resolve => { finish = resolve }))
  const result = f.api.edit(0, {}, context, 'feature'); f.change(kind)
  finish({ design: { id: 'part' }, revision: 5, nucleotides: [] })
  await expect(result).rejects.toThrow(/changed|current/i); expect(f.syncDesign).not.toHaveBeenCalled()
})
it.each([null, { design: { id: 'part' }, revision: 5 }, { design: { id: 'part' }, revision: 5, nucleotides: [], partial_geometry: true }])('refuses null or incomplete geometry before synchronization', async response => {
  const f = fixture(); f.request.mockResolvedValue(response)
  await expect(f.api.edit(0, {}, f.api.capture(), 'feature')).rejects.toThrow()
  expect(f.syncDesign).not.toHaveBeenCalled()
})
it('requires original feature and a known source revision before dispatch', async () => {
  const f = fixture(), context = f.api.capture()
  await expect(f.api.edit(0, {}, context, 'replacement')).rejects.toThrow(/feature/i)
  await expect(f.api.edit(0, {}, { ...context, revision: null }, 'feature')).rejects.toThrow()
  expect(f.request).not.toHaveBeenCalled()
})
it('does not describe an empty response as a confirmed server rejection', async () => {
  const f = fixture(); f.request.mockResolvedValue(null)
  await expect(f.api.edit(0, {}, f.api.capture(), 'feature')).rejects.toThrow('No confirmed extrusion result; refresh before retrying.')
  expect(f.syncDesign).not.toHaveBeenCalled()
})

it('names the failing downstream child and retains its structured failure without adoption', async () => {
  const f = fixture(), context = f.api.capture()
  context.source.feature_log.push({ id: 'routing', feature_type: 'routing-cluster', children: [
    { id: 'nick', label: 'Output nick' },
  ] })
  const detail = { code: 'missing_reference', assessment: { issues: [
    { feature_id: 'nick', detail: 'Target is no longer occupied', references: [{ identity: 'target' }] },
  ] } }
  f.request.mockImplementation(async (_method, _path, _body, options) => {
    options.onError(409, detail)
    return null
  })
  await expect(f.api.edit(0, {}, context, 'feature')).rejects.toMatchObject({
    message: 'F2 routing-cluster / Output nick cannot regenerate after this edit: Target is no longer occupied',
    status: 409, detail,
  })
  expect(f.syncDesign).not.toHaveBeenCalled()
})
