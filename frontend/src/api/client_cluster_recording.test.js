import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { patchCluster, getPersistedDesign, resetRevisionWatermark } from './client.js'
import * as client from './client.js'
import { store } from '../state/store.js'
import { nadocBroadcast } from '../shared/broadcast.js'
import { activeOperationTiming, finishOperationTiming } from '../perf/operation_timing.js'

vi.mock('../shared/broadcast.js', () => ({ nadocBroadcast: { emit: vi.fn() } }))
vi.mock('../shared/connection_monitor.js', () => ({
  notifyRequestSuccess: vi.fn(), notifyRequestFailure: vi.fn(), pokeProbe: vi.fn(),
}))

const response = (payload, status = 200) => ({ ok: status < 400, status, headers: new Headers(), json: async () => payload })
const original = () => ({ id: 'groups', helices: [], strands: [],
  cluster_transforms: [{ id: 'group', name: 'Before', helix_ids: ['h'], domain_ids: [], translation: [0, 0, 0] }],
  feature_log: [{ id: 'old', post_state_gz_b64: 'retained-recovery' }], feature_log_cursor: -1 })
function payload(revision = 1, fields = {}) {
  const design = original()
  design.cluster_transforms[0] = { ...design.cluster_transforms[0], ...fields }
  design.feature_log = [{ id: 'old', post_state_gz_b64: '' }, { id: 'new', feature_type: 'cluster_op' }]
  return { design, revision, feature_log_payloads_partial: true, validation: { passed: true, loop_strand_ids: [] } }
}
const geometryPayload = (x = 7) => ({
  nucleotides: [{ helix_id: 'h', bp_index: 0, position: [x, 0, 0] }],
  helix_axes: [{ helix_id: 'h', start: [x, 0, 0], end: [x, 0, 10] }],
})
function transport(value) {
  const fetch = vi.fn(async url => url === '/api/design/geometry'
    ? response(geometryPayload()) : response(value))
  vi.stubGlobal('fetch', fetch); return fetch
}
beforeEach(() => {
  resetRevisionWatermark(); localStorage.clear(); vi.clearAllMocks()
  store.setState({ currentDesign: original(), currentGeometry: [{ helix_id: 'h', bp_index: 0, position: [0, 0, 0] }],
    currentHelixAxes: { h: { start: [0, 0, 0], end: [0, 0, 10] } }, loopStrandIds: ['retained-loop'],
    assemblyActive: false, featureSeekPending: false, lastError: null, isolatedStrandId: null })
})
afterEach(() => {
  window.dispatchEvent(new Event('nadoc:document-reset'))
  while (activeOperationTiming()) finishOperationTiming(activeOperationTiming(), { status: 'Superseded' })
  localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals()
})

it.each([{ name: 'Renamed' }, { name: '' }, { color: '#123456' }, { color: '' }, { opacity: 0 }, { opacity: 0.4 }])(
  'records ordinary group edit %j even when a caller requests log:false and commit:false', async fields => {
    const result = payload(1, fields), fetch = transport(result), beforeGeometry = store.getState().currentGeometry
    const beforeAxes = store.getState().currentHelixAxes, body = Object.freeze({ ...fields, commit: false, log: false })
    expect(await patchCluster('group', body)).toBe(result)
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ ...body, commit: true })
    expect(body.commit).toBe(false)
    expect(fetch.mock.calls.map(call => call[0])).toEqual(['/api/design/cluster/group'])
    expect(store.getState().currentDesign.cluster_transforms[0]).toMatchObject(fields)
    expect(store.getState().validationReport).toBe(result.validation)
    expect(store.getState().currentGeometry).toBe(beforeGeometry); expect(store.getState().currentHelixAxes).toBe(beforeAxes)
    expect(getPersistedDesign().feature_log[0].post_state_gz_b64).toBe('retained-recovery')
    expect(getPersistedDesign().feature_log.at(-1).feature_type).toBe('cluster_op')
    expect(nadocBroadcast.emit).toHaveBeenCalledExactlyOnceWith('design-changed', expect.objectContaining({ geometry_unchanged: true }))
  },
)

it.each([{ helix_ids: ['h', 'other'] }, { helix_ids: [] }, { domain_ids: [{ strand_id: 's', domain_index: 0 }] }, { domain_ids: [] }])(
  'adopts committed membership %j with its authoritative embedded geometry in one response', async fields => {
    const result = { ...payload(1, fields), ...geometryPayload() }, fetch = transport(result)
    await patchCluster('group', { ...fields, translation: [7, 0, 0], commit: false })
    expect(JSON.parse(fetch.mock.calls[0][1].body).commit).toBe(true)
    expect(fetch.mock.calls.map(call => call[0])).toEqual(['/api/design/cluster/group'])
    expect(store.getState().currentGeometry[0].position).toEqual([7, 0, 0])
    expect(store.getState().currentHelixAxes.h.start).toEqual([7, 0, 0])
    expect(getPersistedDesign().cluster_transforms[0]).toMatchObject(fields)
    expect(nadocBroadcast.emit).toHaveBeenCalledExactlyOnceWith('design-changed', expect.objectContaining({ geometry_unchanged: false }))
  },
)

it.each([
  { name: 'Moved', translation: [7, 0, 0] },
  { color: '#123456', rotation: [0, 0, 1, 0] },
  { name: 'Repivoted', pivot: [7, 0, 0] },
])('refreshes geometry for a mixed ordinary edit and explicit pose %j', async fields => {
  const fetch = transport({ ...payload(1, fields), ...geometryPayload() })
  await patchCluster('group', { ...fields, commit: false })
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ ...fields, commit: true })
  expect(fetch.mock.calls.map(call => call[0])).toEqual(['/api/design/cluster/group'])
  expect(store.getState().currentGeometry[0].position).toEqual([7, 0, 0])
  expect(store.getState().currentHelixAxes.h.start).toEqual([7, 0, 0])
  expect(getPersistedDesign().cluster_transforms[0]).toMatchObject(fields)
  expect(nadocBroadcast.emit).toHaveBeenCalledExactlyOnceWith('design-changed', expect.objectContaining({ geometry_unchanged: false }))
})

it('retains the shared geometry-fetch fallback for an older server without embedded membership geometry', async () => {
  const fetch = transport(payload(1, { helix_ids: ['h'] }))
  await patchCluster('group', { helix_ids: ['h'] })
  expect(fetch.mock.calls.map(call => call[0])).toEqual(['/api/design/cluster/group', '/api/design/geometry'])
  expect(store.getState().currentGeometry[0].position).toEqual([7, 0, 0])
  expect(getPersistedDesign().cluster_transforms[0].helix_ids).toEqual(['h'])
})

it('does not treat null membership or pose fields as a geometry change during a name edit', async () => {
  const fetch = transport(payload(1, { name: 'Named' })), geometry = store.getState().currentGeometry
  await patchCluster('group', { name: 'Named', helix_ids: null, domain_ids: null, translation: null, rotation: null, pivot: null })
  expect(JSON.parse(fetch.mock.calls[0][1].body).commit).toBe(true)
  expect(fetch).toHaveBeenCalledTimes(1); expect(store.getState().currentGeometry).toBe(geometry)
})

it.each([{}, { name: null, color: null, opacity: null, helix_ids: null, domain_ids: null }])(
  'keeps pose-only live previews transient on the existing lightweight path %j', async fields => {
    const result = payload(1, { translation: [7, 0, 0] }), fetch = transport(result)
    const geometry = store.getState().currentGeometry, loops = store.getState().loopStrandIds
    const body = { ...fields, translation: [7, 0, 0], commit: false }
    await patchCluster('group', body)
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(body)
    expect(fetch).toHaveBeenCalledTimes(1); expect(store.getState().currentGeometry).toBe(geometry)
    expect(store.getState().loopStrandIds).toBe(loops)
    expect(store.getState().currentDesign.cluster_transforms[0].translation).toEqual([7, 0, 0])
    expect(getPersistedDesign()).toBeNull(); expect(nadocBroadcast.emit).not.toHaveBeenCalled()
  },
)

it('keeps committed pose geometry under the existing gizmo-owned contract while persisting history', async () => {
  const fetch = transport(payload(1, { translation: [7, 0, 0] })), geometry = store.getState().currentGeometry
  await patchCluster('group', { translation: [7, 0, 0], commit: true })
  expect(fetch).toHaveBeenCalledTimes(1); expect(store.getState().currentGeometry).toBe(geometry)
  expect(getPersistedDesign().feature_log).toHaveLength(2)
  expect(nadocBroadcast.emit).toHaveBeenCalledTimes(1)
})

it('leaves design, cached geometry and persisted history untouched when an ordinary edit is refused', async () => {
  const design = store.getState().currentDesign, geometry = store.getState().currentGeometry
  vi.stubGlobal('fetch', vi.fn(async () => response({ detail: { code: 'missing_reference', message: 'Missing group member' } }, 422)))
  expect(await patchCluster('group', { helix_ids: ['missing'] })).toBeNull()
  expect(store.getState().currentDesign).toBe(design); expect(store.getState().currentGeometry).toBe(geometry)
  expect(store.getState().lastError).toMatchObject({ status: 422 })
  expect(getPersistedDesign()).toBeNull(); expect(nadocBroadcast.emit).not.toHaveBeenCalled()
})

it('drops older embedded membership geometry and Design together after a newer committed response', async () => {
  const pending = []
  vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise(resolve => pending.push({ resolve, body: JSON.parse(options.body) }))))
  const old = patchCluster('group', { helix_ids: [] }), newer = patchCluster('group', { name: 'Latest', helix_ids: ['h'] })
  await vi.waitFor(() => expect(pending).toHaveLength(2))
  const latest = { ...payload(3, { name: 'Latest', helix_ids: ['h'] }), ...geometryPayload(9) }
  pending[1].resolve(response(latest)); await newer
  const geometry = store.getState().currentGeometry
  pending[0].resolve(response({ ...payload(2, { helix_ids: [] }), ...geometryPayload(2) })); await old
  expect(store.getState().currentDesign.cluster_transforms[0].name).toBe('Latest')
  expect(getPersistedDesign().cluster_transforms[0].name).toBe('Latest')
  expect(store.getState().currentGeometry).toBe(geometry); expect(geometry).toBe(latest.nucleotides)
  expect(store.getState().currentHelixAxes.h.start).toEqual([9, 0, 0]); expect(fetch).toHaveBeenCalledTimes(2)
  expect(nadocBroadcast.emit).toHaveBeenCalledTimes(1)
})

it('ignores a completed ordinary edit after the document is replaced, even if fetch ignores abort', async () => {
  let resolve
  vi.stubGlobal('fetch', vi.fn(() => new Promise(done => { resolve = done })))
  const pending = patchCluster('group', { helix_ids: [] })
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  window.dispatchEvent(new Event('nadoc:document-reset'))
  const geometry = store.getState().currentGeometry
  const replacement = { ...original(), id: 'replacement' }; store.setState({ currentDesign: replacement })
  resolve(response({ ...payload(100, { helix_ids: [] }), ...geometryPayload() }))
  expect(await pending).toBeNull(); expect(store.getState().currentDesign).toBe(replacement)
  expect(store.getState().currentGeometry).toBe(geometry)
  expect(getPersistedDesign()).toBeNull(); expect(nadocBroadcast.emit).not.toHaveBeenCalled()
})

const dissolvedPayload = (revision = 1) => {
  const result = { ...payload(revision), ...geometryPayload() }
  result.design.cluster_transforms = []
  result.design.feature_log.at(-1).op_kind = 'cluster-dissolve'
  return result
}

it.each(['single', 'batch'])('adopts a %s dissolve with its exact geometry and one recorded response', async mode => {
  const result = dissolvedPayload(), fetch = transport(result)
  const ids = Object.freeze(['group', 'other'])
  expect(await (mode === 'single' ? client.deleteCluster('group') : client.dissolveClusters(ids))).toBe(result)
  expect(fetch).toHaveBeenCalledTimes(1)
  const [url, request] = fetch.mock.calls[0]
  expect(url).toBe(mode === 'single' ? '/api/design/cluster/group' : '/api/design/clusters/dissolve')
  expect(request.method).toBe(mode === 'single' ? 'DELETE' : 'POST')
  if (mode === 'batch') expect(JSON.parse(request.body)).toEqual({ cluster_ids: ['group', 'other'] })
  expect(store.getState().currentDesign.cluster_transforms).toEqual([])
  expect(store.getState().currentGeometry).toBe(result.nucleotides)
  expect(store.getState().currentHelixAxes.h.start).toEqual([7, 0, 0])
  expect(getPersistedDesign().feature_log[0].post_state_gz_b64).toBe('retained-recovery')
  expect(getPersistedDesign().feature_log.at(-1).op_kind).toBe('cluster-dissolve')
  expect(nadocBroadcast.emit).toHaveBeenCalledTimes(1)
})

it.each(['single', 'batch'])('preserves all browser state when %s dissolve is refused', async mode => {
  const before = store.getState()
  vi.stubGlobal('fetch', vi.fn(async () => response({ detail: { code: 'group_has_dependencies', message: 'Group is required by a bend' } }, 409)))
  expect(await (mode === 'single' ? client.deleteCluster('group') : client.dissolveClusters(['group']))).toBeNull()
  expect(store.getState().currentDesign).toBe(before.currentDesign)
  expect(store.getState().currentGeometry).toBe(before.currentGeometry)
  expect(store.getState().lastError).toMatchObject({ status: 409 })
  expect(getPersistedDesign()).toBeNull(); expect(nadocBroadcast.emit).not.toHaveBeenCalled()
})

it('does not adopt a late dissolve over a newer same-document edit', async () => {
  const pending = []
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => pending.push(resolve))))
  const old = client.dissolveClusters(['group']), newer = patchCluster('group', { name: 'Retained', helix_ids: ['h'] })
  await vi.waitFor(() => expect(pending).toHaveLength(2))
  const latest = { ...payload(3, { name: 'Retained' }), ...geometryPayload(9) }
  pending[1](response(latest)); await newer
  pending[0](response(dissolvedPayload(2))); await old
  expect(store.getState().currentDesign.cluster_transforms[0].name).toBe('Retained')
  expect(store.getState().currentGeometry).toBe(latest.nucleotides)
  expect(getPersistedDesign().cluster_transforms[0].name).toBe('Retained')
  expect(nadocBroadcast.emit).toHaveBeenCalledTimes(1)
})

it('returns null for a dissolve cancelled by document replacement even when fetch ignores abort', async () => {
  let resolve
  vi.stubGlobal('fetch', vi.fn(() => new Promise(done => { resolve = done })))
  const pending = client.dissolveClusters(['group'])
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  window.dispatchEvent(new Event('nadoc:document-reset'))
  const replacement = { ...original(), id: 'replacement' }; store.setState({ currentDesign: replacement })
  resolve(response(dissolvedPayload(10)))
  expect(await pending).toBeNull(); expect(store.getState().currentDesign).toBe(replacement)
  expect(getPersistedDesign()).toBeNull(); expect(nadocBroadcast.emit).not.toHaveBeenCalled()
})
