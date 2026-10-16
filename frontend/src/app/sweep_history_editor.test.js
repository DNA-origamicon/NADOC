import { afterEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { sweepPacket } from '../test-helpers/sweep_preview.js'
import { createSweepHistoryEditor } from './sweep_history_editor.js'

const owned = [], tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }
function fixture() {
  let revision = 7
  const packet = body => ({ ...sweepPacket({ envelope: true }), ...body, request_sequence: body.request_sequence ?? 0 })
  const source = { id: 'part', feature_log_cursor: -1, helices: [{ id: 'latest-only' }], feature_log: [{ id: 'feature', params: { sweep_id: 'saved' } }] }
  const store = createMockStore({ currentDesign: source }), events = new EventTarget()
  const api = { currentRevisionWatermark: () => revision, syncDesignResponse: vi.fn(value => {
    revision = value.revision; store.setState({ currentDesign: value.design }); return Promise.resolve(value)
  }) }
  const previewAPI = { prepare: vi.fn(async body => packet(body)), evaluate: vi.fn(async body => ({ ...packet(body), candidate: body.include_geometry ? sweepPacket().candidate : null })),
    cancel: vi.fn(async () => ({ status: 'cancelled' })), apply: vi.fn(async body => ({ ...packet(body), status: 'applied', design_id: 'part', revision: 8 })),
    status: vi.fn(), refreshCommitted: vi.fn(async () => ({ design: { ...source }, revision: 8 })) }
  const preview = { open: vi.fn(), replaceCandidate: vi.fn(), show: vi.fn(), dispose: vi.fn() }
  const view = { open: vi.fn(), close: vi.fn(), updatePreview: vi.fn(), setStatus: vi.fn() }
  const release = vi.fn(), slicePlane = { usePrivateContext: vi.fn(() => release) }
  const owner = createSweepHistoryEditor({ store, api, previewAPI, view, slicePlane, getDocumentId: () => 'doc',
    createPreview: () => preview, validateDisplay: value => value, events, showToast: vi.fn() })
  owned.push(owner)
  return { owner, store, source, api, previewAPI, preview, view, slicePlane, release, events, packet,
    session: () => view.open.mock.lastCall[1] }
}
afterEach(() => { for (const owner of owned.splice(0)) owner.dispose() })
it('opens saved Sweep on fixed prefix controls and private picker, without canonical writes', async () => {
  const f = fixture(); expect(await f.owner.open(f.source.feature_log[0], 0)).toBe(true)
  expect(f.previewAPI.prepare.mock.lastCall[0].feature_id).toBe('feature')
  expect(f.view.open.mock.lastCall[0]).toEqual(sweepPacket().control_context.inputs)
  expect(f.session().design.helices.map(h => h.id)).toEqual(['h'])
  expect(f.slicePlane.usePrivateContext.mock.lastCall[0].design).toBe(f.session().design)
  expect(f.api.syncDesignResponse).not.toHaveBeenCalled(); expect(f.store.getState().currentDesign).toBe(f.source)
  expect(await f.session().onCancel()).toBe(true); expect(f.release).toHaveBeenCalledOnce(); expect(f.preview.dispose).toHaveBeenCalledOnce()
})
it('coalesces complete native controls and keeps visual-off feasibility with the fixed prefix', async () => {
  const f = fixture(); await f.owner.open(f.source.feature_log[0], 0)
  const patch = { cells: [[1, 2]], plane: 'YZ', source_helix_id: 'h', source_end: 'start', detach_source: true,
    strand_filter: 'staples', ligate_adjacent: false, points_nm: [[2, 0, 0], [8, 1, 3]], orientations_deg: [null, [10, 20, 30]] }
  await f.session().onChange(patch, { includeGeometry: false })
  expect(f.previewAPI.evaluate.mock.lastCall[0]).toMatchObject({ params: patch, include_geometry: false })
  expect(f.preview.show).toHaveBeenLastCalledWith('before')
  expect(f.view.updatePreview).toHaveBeenCalledWith(expect.objectContaining({ source_frame: expect.any(Object) }))
  expect(f.api.syncDesignResponse).not.toHaveBeenCalled()
})
it('keeps failed Apply usable and adopts a confirmed retry only once', async () => {
  const f = fixture(); await f.owner.open(f.source.feature_log[0], 0)
  f.previewAPI.apply.mockRejectedValueOnce(Object.assign(new Error('Downstream nick missing'), { status: 422 }))
  expect(await f.session().onApply()).toBe(false); expect(f.owner.active()).toBe(true)
  expect(await f.session().onApply()).toBe(true); expect(f.api.syncDesignResponse).toHaveBeenCalledOnce()
  expect(f.owner.active()).toBe(false); expect(f.release).toHaveBeenCalledOnce()
})
it('keeps an unknown Apply unresolved until status, never automatically recommits', async () => {
  const f = fixture(); await f.owner.open(f.source.feature_log[0], 0)
  f.previewAPI.apply.mockRejectedValueOnce(new Error('Disconnected'))
  expect(await f.session().onApply()).toBe(false)
  f.previewAPI.status.mockResolvedValue({ ...f.packet(f.previewAPI.apply.mock.lastCall[0]), status: 'applying' })
  expect(await f.session().onApply()).toBe(false)
  expect(f.previewAPI.apply).toHaveBeenCalledOnce(); expect(f.owner.active()).toBe(true)
})
it('same-ID reset retires held Prepare and permits reopening before the old result', async () => {
  const f = fixture(); let resolve
  f.previewAPI.prepare.mockImplementationOnce(body => new Promise(done => { resolve = () => done(f.packet(body)) }))
  const old = f.owner.open(f.source.feature_log[0], 0); f.events.dispatchEvent(new Event('nadoc:document-reset'))
  expect(f.owner.active()).toBe(false); expect(await f.owner.open(f.source.feature_log[0], 0)).toBe(true)
  resolve(); expect(await old).toBe(false); expect(f.owner.active()).toBe(true); expect(f.preview.dispose).not.toHaveBeenCalled()
})
it('ignores late evaluation after document replacement and never restores the old model', async () => {
  const f = fixture(); await f.owner.open(f.source.feature_log[0], 0); let resolve
  f.previewAPI.evaluate.mockImplementationOnce(body => new Promise(done => { resolve = () => done(f.packet(body)) }))
  const pending = f.session().onChange({ points_nm: [[0, 0, 0], [0, 0, 4]] })
  const replacement = { id: 'other' }; f.store.setState({ currentDesign: replacement }); resolve(); await pending; await tick()
  expect(f.owner.active()).toBe(false); expect(f.store.getState().currentDesign).toBe(replacement); expect(f.api.syncDesignResponse).not.toHaveBeenCalled()
})
