import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import * as client from './client.js'
import { store } from '../state/store.js'
import { getDocId } from '../shared/doc_id.js'
import { nadocBroadcast } from '../shared/broadcast.js'
import { activeOperationTiming, finishOperationTiming } from '../perf/operation_timing.js'

vi.mock('../shared/broadcast.js', () => ({ nadocBroadcast: { emit: vi.fn() } }))
vi.mock('../shared/connection_monitor.js', () => ({ notifyRequestSuccess: vi.fn(), notifyRequestFailure: vi.fn(), pokeProbe: vi.fn() }))
const response = (payload, status = 200) => ({ ok: status < 400, status, headers: new Headers(), json: async () => payload })
const design = () => ({ id: 'part', helices: [], strands: [], cluster_transforms: [],
  group_organization: { version: 1, groups: [] }, feature_log: [], feature_log_cursor: -1 })
const payload = (revision, name = 'New') => ({ revision, design: { ...design(), name }, validation: { passed: true, loop_strand_ids: [] } })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
beforeEach(async () => {
  client.resetRevisionWatermark(); localStorage.clear(); vi.clearAllMocks()
  store.setState({ currentDesign: design(), currentGeometry: [], currentHelixAxes: {}, assemblyActive: false,
    featureSeekPending: false, lastError: null })
  await client._syncFromDesignResponse(payload(7, 'Source'), { skipGeometry: true })
  vi.clearAllMocks()
})
afterEach(() => {
  window.dispatchEvent(new Event('nadoc:document-reset'))
  while (activeOperationTiming()) finishOperationTiming(activeOperationTiming(), { status: 'Superseded' })
  localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals()
})
it.each(['group-organize', 'group-create', 'group-update', 'group-dissolve'])('sends %s with captured revision/doc and adopts metadata without geometry fetch', async kind => {
  const result = payload(8), inputs = Object.freeze({ group_id: 'g' })
  const fetch = vi.fn(async () => response(result)); vi.stubGlobal('fetch', fetch)
  const geometry = store.getState().currentGeometry
  expect(await client.groupOrganizationCommand(kind, inputs)).toBe(result)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0][0]).toBe('/api/design/group-organization/commands')
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ kind, inputs, expected_revision: 7 })
  expect(fetch.mock.calls[0][1].headers['X-NADOC-Doc']).toBe(getDocId() ?? undefined)
  expect(store.getState().currentGeometry).toBe(geometry)
  expect(client.getPersistedDesign().name).toBe('New')
  expect(nadocBroadcast.emit).toHaveBeenCalledTimes(1)
})
it.each(['placement-update', 'placements-update'])('adopts embedded exact geometry for %s without another request', async kind => {
  const result = { ...payload(8), nucleotides: [], helix_axes: [] }
  const fetch = vi.fn(async () => response(result)); vi.stubGlobal('fetch', fetch)
  expect(await client.groupOrganizationCommand(kind, { placements: [] })).toBe(result)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(store.getState().currentGeometry).toBe(result.nucleotides)
})
it('returns null on refusal without touching authoring or persisted state', async () => {
  const before = store.getState().currentDesign, persisted = client.getPersistedDesign()
  vi.stubGlobal('fetch', vi.fn(async () => response({ detail: { code: 'missing_reference', message: 'Missing group' } }, 422)))
  expect(await client.groupOrganizationCommand('group-update', { group_id: 'missing' })).toBeNull()
  expect(store.getState().currentDesign).toBe(before)
  expect(client.getPersistedDesign()).toEqual(persisted)
  expect(nadocBroadcast.emit).not.toHaveBeenCalled()
})
it('returns null for an older same-document response while retaining newer groups', async () => {
  const old = deferred(); let call = 0
  vi.stubGlobal('fetch', vi.fn(() => ++call === 1 ? old.promise : Promise.resolve(response(payload(9, 'Newest')))))
  const pending = client.groupOrganizationCommand('group-update', {})
  await Promise.resolve()
  await client.groupOrganizationCommand('group-update', {})
  old.resolve(response(payload(8, 'Older')))
  expect(await pending).toBeNull()
  expect(store.getState().currentDesign.name).toBe('Newest')
})
it.each(['replace', 'reset'])('refuses late adoption after document %s, including same-ID reset', async mode => {
  const wait = deferred(); vi.stubGlobal('fetch', vi.fn(() => wait.promise))
  const pending = client.groupOrganizationCommand('group-update', {})
  await Promise.resolve()
  if (mode === 'replace') store.setState({ currentDesign: { ...design(), id: 'other' } })
  else window.dispatchEvent(new Event('nadoc:document-reset'))
  const current = store.getState().currentDesign
  wait.resolve(response(payload(8)))
  expect(await pending).toBeNull()
  expect(store.getState().currentDesign).toBe(current)
  expect(nadocBroadcast.emit).not.toHaveBeenCalled()
})
it('refuses an unbound revision before sending a command', async () => {
  client.resetRevisionWatermark(); const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
  expect(await client.groupOrganizationCommand('group-create', {})).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
})
it('rejects a pose response without its exact geometry instead of fetching a later revision', async () => {
  const fetch = vi.fn(async () => response(payload(8))); vi.stubGlobal('fetch', fetch)
  const before = store.getState().currentDesign
  expect(await client.groupOrganizationCommand('placement-update', {})).toBeNull()
  expect(fetch).toHaveBeenCalledTimes(1); expect(store.getState().currentDesign).toBe(before)
})

it('persists active group visibility through the owned presentation command', async () => {
  const visibility = { hidden_base_keys: ['h:0:FORWARD'], shown_base_keys: [], hidden_cluster_ids: [] }
  const result = { ...payload(8), design: { ...design(), visibility_state: visibility } }
  const fetch = vi.fn(async () => response(result)); vi.stubGlobal('fetch', fetch)
  expect(await client.saveVisibilityState(visibility)).toBe(result)
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ kind: 'visibility-update',
    inputs: { visibility_state: visibility }, expected_revision: 7 })
  expect(fetch.mock.calls[0][0]).toBe('/api/design/group-organization/commands')
  expect(client.getPersistedDesign().visibility_state).toEqual(visibility)
})

it('keeps the legacy visibility endpoint unchanged', async () => {
  const legacy = design(); delete legacy.group_organization
  store.setState({ currentDesign: legacy })
  const fetch = vi.fn(async () => response({ ...payload(8), design: legacy })); vi.stubGlobal('fetch', fetch)
  await client.saveVisibilityState({ hidden_base_keys: ['h:0:FORWARD'] })
  expect(fetch.mock.calls[0][0]).toBe('/api/design/visibility')
  expect(fetch.mock.calls[0][1].method).toBe('PUT')
})
