import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createDeformationHistoryEditor } from './deformation_history_editor.js'

const LEASE = '22222222-2222-4222-8222-222222222222'
const op = { id: 'bend', type: 'bend', plane_a_bp: 0, plane_b_bp: 8,
  cluster_ids: [], params: { kind: 'bend', curvature_deg_per_bp: .123456, direction_deg: 0 } }
const owned = []
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }
function setup() {
  const design = { id: 'part', feature_log_cursor: -1, feature_log: [{ id: 'feature', feature_type: 'deformation', op_snapshot: op }] }
  const store = createMockStore({ currentDesign: design }), before = { helix_axes: [{ helix_id: 'h', start: [0, 0, 0], end: [0, 0, 3] }] }
  let revision = 7, doc = 'doc'
  const packet = body => ({ preview_id: body.preview_id, expected_design_id: 'part', expected_revision: 7,
    feature_id: 'feature', lease_id: LEASE, doc_id: 'doc', deformation_id: 'bend', request_sequence: body.request_sequence ?? 0,
    remaining_seconds: 60, before, candidate: { which: 'candidate' }, feasibility: { status: 'ok' },
    control_context: { helices: [], strands: [], cluster_transforms: [], deformations: [], forced_ligations: [], selected_operation: op } })
  const previewAPI = { prepare: vi.fn(async body => packet(body)), evaluate: vi.fn(async body => ({ ...packet(body), candidate: body.include_geometry ? { which: 'new' } : null })),
    cancel: vi.fn(async () => ({ status: 'cancelled' })),
    apply: vi.fn(async body => ({ ...packet(body), status: 'applied', design_id: 'part', revision: 8 })),
    refreshCommitted: vi.fn(async () => ({ design: { ...design }, revision: 8 })), status: vi.fn() }
  const api = { currentRevisionWatermark: () => revision, syncDesignResponse: vi.fn(value => {
    revision = value.revision; store.setState({ currentDesign: value.design }); return Promise.resolve(value)
  }) }
  const editor = { startToolForHistory: vi.fn(), finishHistoryTool: vi.fn(), repositionPlane: vi.fn() }
  const popup = { openPopup: vi.fn(), closePopup: vi.fn(), setHistoryPopupStatus: vi.fn() }
  const preview = { open: vi.fn(), replaceCandidate: vi.fn(), show: vi.fn(), dispose: vi.fn() }
  const showToast = vi.fn(), setMode = vi.fn()
  const owner = createDeformationHistoryEditor({ store, api, previewAPI, getDocumentId: () => doc,
    editor, popup, showToast, setMode, createPreview: () => preview, validateDisplay: value => value,
    events: new EventTarget() })
  owned.push(owner)
  return { owner, store, api, previewAPI, editor, popup, preview, showToast, setMode, design,
    session: () => popup.openPopup.mock.calls.at(-1)[6], packet,
    switchDocument() { doc = 'other'; store.setState({ currentDesign: { ...design, id: 'other' } }) } }
}
afterEach(() => { for (const item of owned.splice(0)) item.dispose() })

describe('deformation history editor integration', () => {
  it('opens fixed-prefix scene and controls by feature identity without canonical edits', async () => {
    const f = setup(); await f.owner.open(f.design.feature_log[0], 0)
    expect(f.previewAPI.prepare.mock.calls[0][0].feature_id).toBe('feature')
    expect(f.editor.startToolForHistory).toHaveBeenCalledWith(op, expect.objectContaining({ design: expect.objectContaining({ cluster_transforms: [] }), helixAxes: expect.objectContaining({ h: expect.any(Object) }) }))
    expect(f.popup.openPopup.mock.calls[0].slice(0, 6)).toEqual(['bend', 0, 8, op.params, [], true])
    expect(f.api.syncDesignResponse).not.toHaveBeenCalled(); expect(f.previewAPI.evaluate).not.toHaveBeenCalled()
    await f.session().onCancel()
    expect(f.owner.active()).toBe(false); expect(f.preview.dispose).toHaveBeenCalledOnce()
    expect(f.editor.finishHistoryTool).toHaveBeenCalledOnce()
    expect(f.api.syncDesignResponse).not.toHaveBeenCalled()
  })

  it('visual-off shows the fixed prefix and still evaluates native feasibility', async () => {
    const f = setup(); await f.owner.open(f.design.feature_log[0], 0)
    await f.session().onChange({ plane_b_bp: 9 }, { includeGeometry: false })
    expect(f.previewAPI.evaluate.mock.calls[0][0]).toMatchObject({ params: { plane_b_bp: 9 }, include_geometry: false })
    expect(f.preview.show).toHaveBeenLastCalledWith('before')
    expect(f.preview.replaceCandidate).toHaveBeenLastCalledWith(null)
    expect(f.popup.setHistoryPopupStatus).toHaveBeenLastCalledWith(expect.objectContaining({ feasibility: { status: 'ok' } }))
    expect(f.api.syncDesignResponse).not.toHaveBeenCalled()
  })

  it('unchanged Apply retains exact inputs, adopts once and tears down local display', async () => {
    const f = setup(); await f.owner.open(f.design.feature_log[0], 0)
    expect(await f.session().onApply({})).toBe(true)
    expect(f.previewAPI.apply.mock.calls[0][0].params).toEqual({})
    expect(f.previewAPI.evaluate).not.toHaveBeenCalled()
    expect(f.api.syncDesignResponse).toHaveBeenCalledOnce()
    expect(f.owner.active()).toBe(false); expect(f.preview.dispose).toHaveBeenCalledOnce()
  })

  it('keeps the prefix visible and blocks Apply when a replacement cannot be rendered', async () => {
    const f = setup(); await f.owner.open(f.design.feature_log[0], 0)
    await f.session().onChange({}, { includeGeometry: false })
    f.preview.replaceCandidate.mockImplementationOnce(() => { throw new Error('Native display unavailable') })
    await f.session().onChange({}, { includeGeometry: true })
    expect(f.preview.show).toHaveBeenLastCalledWith('before')
    expect(await f.session().onApply({})).toBe(false)
    expect(f.previewAPI.apply).not.toHaveBeenCalled()
    expect(f.popup.setHistoryPopupStatus).toHaveBeenLastCalledWith(expect.objectContaining({ error: expect.objectContaining({ message: 'Native display unavailable' }) }))
  })

  it('keeps failed Apply editable and submits current checked groups on retry', async () => {
    const f = setup(); await f.owner.open(f.design.feature_log[0], 0)
    f.previewAPI.apply.mockRejectedValueOnce(Object.assign(new Error('Broken downstream reference'), { status: 422 }))
    expect(await f.session().onApply({ cluster_ids: ['new'] })).toBe(false)
    expect(f.owner.active()).toBe(true); expect(f.preview.dispose).not.toHaveBeenCalled()
    expect(f.popup.setHistoryPopupStatus).toHaveBeenLastCalledWith(expect.objectContaining({ error: expect.objectContaining({ message: 'Broken downstream reference' }) }))
    expect(await f.session().onApply({ cluster_ids: [] })).toBe(true)
    expect(f.previewAPI.apply.mock.calls[1][0].params.cluster_ids).toEqual([])
  })

  it('document replacement invalidates private work without adopting or restoring the old design', async () => {
    const f = setup(); await f.owner.open(f.design.feature_log[0], 0)
    f.switchDocument(); await tick()
    expect(f.owner.active()).toBe(false); expect(f.preview.dispose).toHaveBeenCalledOnce()
    expect(f.store.getState().currentDesign.id).toBe('other')
    expect(f.api.syncDesignResponse).not.toHaveBeenCalled()
  })

  it('refuses unsupported preparation with an explanation and no canonical fallback', async () => {
    const f = setup(); f.previewAPI.prepare.mockRejectedValue(new Error('Prefix contains unsupported inputs'))
    expect(await f.owner.open(f.design.feature_log[0], 0)).toBe(false)
    expect(f.editor.startToolForHistory).not.toHaveBeenCalled()
    expect(f.showToast).toHaveBeenCalledWith(expect.stringContaining('unsupported inputs'), expect.any(Number))
    expect(f.api.syncDesignResponse).not.toHaveBeenCalled()
    expect(f.owner.active()).toBe(false)
  })

  it('preserves the editor while publication is unresolved and resolves without repeating Apply', async () => {
    const f = setup(); await f.owner.open(f.design.feature_log[0], 0)
    f.previewAPI.apply.mockRejectedValueOnce(new Error('Connection lost'))
    expect(await f.session().onApply({})).toBe(false)
    f.previewAPI.cancel.mockResolvedValue({ status: 'commit_in_progress' })
    expect(await f.session().onCancel()).toBe(false)
    expect(f.owner.active()).toBe(true)
    const body = f.previewAPI.apply.mock.calls[0][0]
    f.previewAPI.status.mockResolvedValue({ ...f.packet(body), status: 'applied', design_id: 'part', revision: 8 })
    expect(await f.session().onApply({})).toBe(true)
    expect(f.previewAPI.apply).toHaveBeenCalledOnce(); expect(f.api.syncDesignResponse).toHaveBeenCalledOnce()
  })
})
