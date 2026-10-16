import { expect, it, vi } from 'vitest'
import { createPatternRequests } from './pattern_requests.js'

function fixture() {
  let state = { currentDesign: { id: 'part', feature_log: [{ id: 'feature' }] }, assemblyActive: false }
  let generation = 0, revision = 7, docId = 'doc'
  const request = vi.fn(async () => ({ design: { id: 'part' }, revision: 8, nucleotides: [], helix_axes: [] }))
  const syncDesign = vi.fn(async packet => { state = { ...state, currentDesign: packet.design }; revision = packet.revision; return packet })
  const api = createPatternRequests({ store: { getState: () => state }, request, syncDesign,
    getDocId: () => docId, currentRevision: () => revision,
    documentRequests: { capture: () => generation, isCurrent: value => value === generation } })
  return { api, request, syncDesign,
    reset: () => { generation++ },
    revision: value => { revision = value },
    document: value => { docId = value },
    replace: () => { state = { ...state, currentDesign: { id: 'part', feature_log: [{ id: 'feature' }] } } },
  }
}

it('dispatches exact frozen source expectations and explicit organization metadata', async () => {
  const f = fixture(), context = f.api.capture()
  const body = { cluster_ids: ['placement'], instances: 2, _organization_copy: { version: 1, group_ids: ['group'] } }
  await f.api.create('linear-pattern', body, context)
  expect(f.request).toHaveBeenCalledWith('POST', '/design/linear-pattern', {
    ...body, expected_design_id: 'part', expected_revision: 7,
  }, { docId: 'doc', protectedRetry: false, skipSimulationPrepare: true })
  expect(f.syncDesign).toHaveBeenCalledTimes(1)
})

it.each(['reset', 'revision', 'document', 'replace'])('refuses stale %s before sending the pattern', async change => {
  const f = fixture(), context = f.api.capture()
  f[change](8)
  await expect(f.api.create('circular-pattern', {}, context)).rejects.toThrow(/changed|current|stale/i)
  expect(f.request).not.toHaveBeenCalled()
  expect(f.syncDesign).not.toHaveBeenCalled()
})

it('ignores a late response after a same-ID reset', async () => {
  const f = fixture(), context = f.api.capture()
  let finish
  f.request.mockReturnValue(new Promise(resolve => { finish = resolve }))
  const result = f.api.create('linear-pattern', {}, context)
  f.reset(); finish({ design: { id: 'part' }, revision: 8 })
  await expect(result).rejects.toThrow(/changed|current|stale/i)
  expect(f.syncDesign).not.toHaveBeenCalled()
})

it('rejects null request and refused canonical synchronization', async () => {
  const f = fixture()
  f.request.mockResolvedValueOnce(null)
  await expect(f.api.create('linear-pattern', {})).rejects.toThrow()
  expect(f.syncDesign).not.toHaveBeenCalled()
  f.syncDesign.mockResolvedValueOnce(null)
  await expect(f.api.create('circular-pattern', {})).rejects.toThrow()
})

it.each([
  ['missing', {}],
  ['wrong type', { nucleotides: {} }],
  ['partial', { nucleotides: [], partial_geometry: true }],
  ['skipped', { nucleotides: [], geometry_skipped: true }],
  ['cluster delta', { nucleotides: [], diff_kind: 'cluster_only' }],
  ['position delta', { nucleotides: [], diff_kind: 'positions_only' }],
])('refuses %s geometry before shared synchronization or source adoption', async (_, geometry) => {
  const f = fixture(), context = f.api.capture()
  f.request.mockResolvedValueOnce({ design: { id: 'part' }, revision: 8, ...geometry })
  await expect(f.api.create('linear-pattern', {}, context)).rejects.toThrow(/geometry|complete/i)
  expect(f.syncDesign).not.toHaveBeenCalled()
  expect(f.api.capture().source).toBe(context.source)
  expect(f.api.capture().revision).toBe(7)
})

it('edits the stable feature with original source expectations and preserves copy metadata', async () => {
  const f = fixture(), context = f.api.capture()
  const params = { instances: 4, _organization_copy: { version: 1, group_ids: ['historical-group'] } }
  await f.api.edit(0, params, context, 'feature')
  expect(f.request).toHaveBeenCalledWith('POST', '/design/features/0/edit', {
    params, expected_design_id: 'part', expected_revision: 7, expected_feature_id: 'feature',
  }, { docId: 'doc', protectedRetry: false, skipSimulationPrepare: true })
  await expect(f.api.edit(0, params, context, 'another')).rejects.toThrow(/feature|changed/i)
  expect(f.request).toHaveBeenCalledTimes(1)
})
