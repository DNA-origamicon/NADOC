import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { _request, _syncFromDesignResponse, currentRevisionWatermark, partRepairAPI, resetRevisionWatermark } from './client.js'
import { store } from '../state/store.js'
import { getDocId } from '../shared/doc_id.js'
import { createPartRepairController } from '../features/part_repair_controller.js'

const design = { id: 'part', active_loadout_id: 'main', helices: [], strands: [], feature_log: [], cluster_transforms: [] }
const response = (json, status = 200) => ({ ok: status < 400, status, statusText: 'Rejected',
  headers: { get: () => null }, json: async () => json })
const context = () => ({ docId: getDocId(), designId: 'part', loadoutId: 'main', revision: currentRevisionWatermark() })

beforeEach(async () => {
  resetRevisionWatermark()
  store.setState({ currentDesign: null, assemblyActive: false, featureSeekPending: false, lastError: null })
  vi.stubGlobal('fetch', vi.fn())
  await _syncFromDesignResponse({ design: { ...design }, revision: 4, nucleotides: [], helix_axes: [] })
  fetch.mockClear()
})
afterEach(() => vi.unstubAllGlobals())

it('delivers typed repair conflicts without activating another loadout', async () => {
  const detail = { code: 'protected_simulation_loadout', detail: 'Read-only loadout',
    feature_id: 'feature', parameter_path: ['target', 'id'] }
  fetch.mockResolvedValue(response({ detail }, 409))
  await expect(partRepairAPI.mutate({ operation: 'rebase' }, { context: context() })).rejects.toMatchObject({ status: 409, detail })
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0][0]).toBe('/api/design/features/repair-draft')
  expect(store.getState().lastError.status).toBe(409)
  expect(store.getState().currentDesign.active_loadout_id).toBe('main')
})

it('keeps the established null/string-error behavior for ordinary API callers', async () => {
  fetch.mockResolvedValue(response({ detail: 'Invalid ordinary edit' }, 422))
  expect(await _request('POST', '/design/test', {}, { suppressBusy: true })).toBeNull()
  expect(store.getState().lastError).toEqual({ status: 422, message: 'Invalid ordinary edit' })
})

it('acknowledges draft metadata without design/geometry refresh or partial draft insertion', async () => {
  const before = store.getState(), origin = context()
  const summary = { draft_id: 'proposal', generation: 1, status: 'pending', base_status: 'unchecked' }
  fetch.mockResolvedValue(response({ design_id: 'part', revision: 5, repair_draft: summary,
    draft: { draft_id: 'proposal', actions: [{ action: 'set_input' }] } }))
  const metadata = await partRepairAPI.mutate({ operation: 'update' }, { context: origin })
  expect(partRepairAPI.acknowledge(metadata, origin)).toBe(true)
  expect(currentRevisionWatermark()).toBe(5)
  expect(store.getState().currentDesign).toBe(before.currentDesign)
  expect(store.getState().currentGeometry).toBe(before.currentGeometry)
  expect(store.getState().currentDesign).not.toHaveProperty('repair_draft')
  expect(store.getState().repairMetadata).toEqual({ designId: 'part', revision: 5, summary })
  expect(fetch).toHaveBeenCalledTimes(1)
  await _syncFromDesignResponse({ design: { ...design }, revision: 4, repair_draft: null,
    nucleotides: [], helix_axes: [] })
  expect(store.getState().repairMetadata.summary).toBe(summary)
})

it('refreshes a real metadata-only commit privately before one design/geometry publication', async () => {
  const draft = { draft_id: 'draft', generation: 0, actions: [] }, summary = { draft_id: 'draft', generation: 0, status: 'pending' }
  let committed = false
  fetch.mockImplementation(async url => {
    if (url === '/api/design/features/repair-draft') return response({ design_id: 'part', revision: 4, draft, repair_draft: summary })
    if (url === '/api/design/features/repair-draft/evaluate') return response({ job_id: 'job', repair_draft: summary })
    if (url === '/api/design/features/evaluation/jobs/job/commit') {
      committed = true
      return response({ job_id: 'job', status: 'committed', revision: 5, design_id: 'part' })
    }
    if (url === '/api/design/features/evaluation/jobs/job') return response(committed
      ? { job_id: 'job', status: 'committed', revision: 5, stale: false, source_busy: false }
      : { job_id: 'job', status: 'complete', stale: false, source_busy: false, result: { status: 'ready', issues: [] } })
    if (url === '/api/design') return response({ design: { ...design }, revision: 5, repair_draft: summary })
    if (url === '/api/design/geometry') return response({ nucleotides: [], helix_axes: [] })
    if (url === '/api/design/revision') return response({ doc_id: getDocId(), design_id: 'part', revision: 5, has_design: true })
    throw new Error(`Unexpected request ${url}`)
  })
  const controller = createPartRepairController({ api: partRepairAPI,
    getContext: () => ({ ...context(), editable: true, cursor: -1, subCursor: null }), subscribeContext: store.subscribe })
  try {
    await controller.inspect(); await controller.evaluate(); await controller.poll()
    const old = store.getState().currentDesign
    expect(controller.getState().ready).toBe(true)
    expect(store.getState().currentDesign).toBe(old)
    await controller.apply()
    expect(controller.getState()).toMatchObject({ committed: { revision: 5 }, refreshNeeded: false, error: null })
    expect(currentRevisionWatermark()).toBe(5)
    expect(store.getState().currentDesign).not.toBe(old)
    expect(fetch.mock.calls.filter(([url]) => url === '/api/design/geometry')).toHaveLength(1)
    expect(fetch.mock.calls.filter(([url]) => url.endsWith('/commit'))).toHaveLength(1)
  } finally { controller.dispose() }
})
