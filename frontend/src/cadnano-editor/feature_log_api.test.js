import { afterEach, describe, expect, it, vi } from 'vitest'
import { editorStore } from './store.js'
import { createFeatureLogStore } from './feature_log_store.js'
import { featureLogAPI, fetchDesign, resetRevisionWatermark } from './api.js'

vi.mock('../shared/broadcast.js', () => ({ nadocBroadcast: { emit: vi.fn() } }))
vi.mock('../shared/doc_id.js', () => ({ getDocId: () => 'editor-doc', docHeaders: () => ({ 'X-NADOC-Doc': 'editor-doc' }), docHeadersFor: id => ({ 'X-NADOC-Doc': id }) }))
vi.mock('../shared/connection_monitor.js', () => ({ notifyRequestSuccess: vi.fn(), notifyRequestFailure: vi.fn() }))
afterEach(() => { resetRevisionWatermark(); vi.unstubAllGlobals() })
const design = () => ({ id: 'part', active_loadout_id: 'main', feature_log: [{ id: 'feature' }] })
const respond = value => ({ ok: true, json: async () => value })

describe('cadnano shared feature log', () => {
  it('preserves transient failure state and propagates design changes through the adapter', () => {
    const store = createFeatureLogStore(editorStore), listener = vi.fn()
    const stop = store.subscribeSlice('ui', listener)
    store.setState({ featureHistoryFailure: { message: 'Refused' } })
    expect(store.getState().featureHistoryFailure.message).toBe('Refused')
    expect(listener).toHaveBeenCalled()
    stop()
  })
  it('publishes source-bound feature edits with full geometry and the editor document header', async () => {
    const source = design(), updated = { ...source, name: 'updated' }
    const fetch = vi.fn().mockResolvedValueOnce(respond({ design: source, revision: 3 }))
      .mockResolvedValueOnce(respond({ design: updated, revision: 4, nucleotides: [], helix_axes: [] }))
    vi.stubGlobal('fetch', fetch)
    await fetchDesign()
    const context = featureLogAPI.captureFeatureEditContext()
    await featureLogAPI.editNativeExtrusionFeature(0, {}, context, 'feature')
    expect(editorStore.getState().design).toBe(updated)
    expect(featureLogAPI.currentRevisionWatermark()).toBe(4)
    const options = fetch.mock.calls[1][1]
    expect(options.headers['X-NADOC-Doc']).toBe('editor-doc')
    expect(options.headers['X-NADOC-Skip-Geometry']).toBeUndefined()
    expect(JSON.parse(options.body).expected_revision).toBe(3)
  })
  it('acknowledges repair metadata without replacing the current topology', async () => {
    const source = design()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ design: source, revision: 3 })))
    await fetchDesign()
    expect(featureLogAPI.partRepairAPI.acknowledge({ design_id: 'part', revision: 4, repair_draft: { actions: 1 } },
      { docId: 'editor-doc', designId: 'part', loadoutId: 'main', revision: 3 })).toBe(true)
    expect(editorStore.getState().design).toBe(source)
    expect(featureLogAPI.currentRevisionWatermark()).toBe(4)
    expect(editorStore.getState().repairMetadata.summary).toEqual({ actions: 1 })
    expect(featureLogAPI.partRepairAPI.acknowledge({ design_id: 'part', revision: 5 },
      { docId: 'other', designId: 'part', loadoutId: 'main', revision: 4 })).toBe(false)
  })
  it('preserves structured repair errors and cancellation signals', async () => {
    const signal = new AbortController().signal
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 409,
      json: async () => ({ detail: { code: 'SOURCE_CHANGED', message: 'Refresh the part' } }) })
    vi.stubGlobal('fetch', fetch)
    await expect(featureLogAPI.partRepairAPI.inspect({ context: { docId: 'editor-doc' }, signal }))
      .rejects.toMatchObject({ status: 409, detail: { code: 'SOURCE_CHANGED' } })
    expect(fetch.mock.calls[0][1].signal).toBe(signal)
  })
})
