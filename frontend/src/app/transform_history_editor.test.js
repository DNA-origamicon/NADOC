import { afterEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { transformPacket } from '../test-helpers/transform_preview.js'
import { createTransformHistoryEditor, isNativeTransformFeature } from './transform_history_editor.js'

const owners = [], lease = '11111111-1111-4111-8111-111111111111'
const tick = async () => { for (let i = 0; i < 10; i++) await Promise.resolve() }
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function fixture(kind = 'cluster_op') {
  let revision = 7
  const source = { id: 'part', feature_log_cursor: -1, feature_log: [{ id: 'feature', feature_type: 'cluster_op', proof_version: 1 }] }
  const store = createMockStore({ currentDesign: source }), events = new EventTarget()
  const packet = body => ({ ...transformPacket(), ...body, command_kind: kind,
    evaluated_command_kind: body.params?.upgrade_to === 'placement-poses-v1' ? 'placement-poses' : kind,
    family: 'transform', lease_id: lease, doc_id: 'doc', request_sequence: body.request_sequence ?? 0, remaining_seconds: 60 })
  const receipt = body => ({ ...body, family: 'transform', command_kind: kind, lease_id: lease,
    doc_id: 'doc', status: 'applied', design_id: 'part', revision: 8 })
  const api = { currentRevisionWatermark: () => revision, syncDesignResponse: vi.fn(value => {
    revision = value.revision; store.setState({ currentDesign: value.design }); return value
  }) }
  const previewAPI = { prepare: vi.fn(async body => packet(body)), evaluate: vi.fn(async body => packet(body)),
    apply: vi.fn(async body => receipt(body)), cancel: vi.fn(async () => ({ status: 'cancelled' })), status: vi.fn(),
    refreshCommitted: vi.fn(async () => ({ design: { ...source }, revision: 8 })) }
  const preview = { open: vi.fn(), replaceCandidate: vi.fn(), show: vi.fn(), dispose: vi.fn() }
  const tool = { open: vi.fn(), update: vi.fn(), setStatus: vi.fn(), dispose: vi.fn(), reset: vi.fn() }
  let callbacks
  const getPanel = vi.fn(() => ({})), createTool = vi.fn(options => { callbacks = options; return tool })
  const editor = createTransformHistoryEditor({ store, api, previewAPI, events, getDocumentId: () => 'doc', getPanel,
    createPreview: () => preview, createTool, validateDisplay: value => value, showToast: vi.fn() })
  owners.push(editor)
  return { editor, source, store, events, api, previewAPI, preview, tool, createTool, getPanel, packet, receipt,
    callbacks: () => callbacks, open: () => editor.open(source.feature_log[0]) }
}
afterEach(() => { for (const owner of owners.splice(0)) owner.dispose() })
it.each(['cluster_op', 'placement-poses', 'nucleotide-transform', 'nucleotide-transform-batch', 'nucleotide-transform-delete'])('owns %s with lazy panel and no canonical preview writes', async kind => {
  const f = fixture(kind); expect(f.getPanel).not.toHaveBeenCalled()
  expect(await f.open()).toBe(true)
  expect(f.getPanel).toHaveBeenCalledOnce(); expect(f.tool.open.mock.lastCall[0].command_kind).toBe(kind)
  expect(f.createTool.mock.lastCall[0].preview).toBe(f.preview)
  await f.callbacks().onChange({ translation: [1, 2, 3] })
  expect(f.previewAPI.evaluate.mock.lastCall[0].params).toEqual({ translation: [1, 2, 3] })
  expect(f.api.syncDesignResponse).not.toHaveBeenCalled(); expect(f.store.getState().currentDesign).toBe(f.source)
  expect(await f.callbacks().onCancel()).toBe(true)
  expect(f.tool.dispose).toHaveBeenCalledOnce(); expect(f.preview.dispose).toHaveBeenCalledOnce()
})
it('replaces the whole accumulated draft on Reset, including explicit upgrade fields', async () => {
  const f = fixture(); await f.open()
  expect(await f.callbacks().onChange({ upgrade_to: 'placement-poses-v1', expected_definition_sha256: 'a'.repeat(64), definition: { poses: [] } }))
    .toMatchObject({ evaluated_command_kind: 'placement-poses' })
  await f.callbacks().onReset()
  expect(f.previewAPI.evaluate.mock.lastCall[0].params).toEqual({})
  await f.callbacks().onApply(); expect(f.previewAPI.apply.mock.lastCall[0].params).toEqual({})
})
it('keeps the panel open after native rejection and publishes one successful retry', async () => {
  const f = fixture(); await f.open()
  f.previewAPI.apply.mockRejectedValueOnce(Object.assign(new Error('Later feature reference is missing'), { status: 422 }))
  expect(await f.callbacks().onApply()).toBe(false); expect(f.tool.dispose).not.toHaveBeenCalled()
  expect(await f.callbacks().onApply()).toBe(true); expect(f.api.syncDesignResponse).toHaveBeenCalledOnce()
})
it('uses status and private refresh after lost Apply, never automatically recommits', async () => {
  const f = fixture(); await f.open(); f.previewAPI.apply.mockRejectedValueOnce(new Error('Disconnected'))
  expect(await f.callbacks().onApply()).toBe(false)
  const body = f.previewAPI.apply.mock.lastCall[0]
  f.previewAPI.status.mockResolvedValue({ ...f.packet(body), status: 'applying' })
  expect(await f.callbacks().onApply()).toBe(false)
  f.previewAPI.status.mockResolvedValue(f.receipt(body))
  expect(await f.callbacks().onApply()).toBe(true)
  expect(f.previewAPI.apply).toHaveBeenCalledOnce(); expect(f.api.syncDesignResponse).toHaveBeenCalledOnce()
})
it('holds the editor while cancellation reports commit in progress', async () => {
  const f = fixture(); await f.open(); const held = deferred(); f.previewAPI.apply.mockReturnValue(held.promise)
  const apply = f.callbacks().onApply(); await tick()
  const body = f.previewAPI.apply.mock.lastCall[0]
  f.previewAPI.cancel.mockResolvedValue({ status: 'commit_in_progress', preview_id: body.preview_id, lease_id: lease })
  expect(await f.callbacks().onCancel()).toBe(false); expect(f.tool.dispose).not.toHaveBeenCalled()
  held.resolve(f.receipt(body)); await apply; expect(f.tool.dispose).toHaveBeenCalledOnce()
})
it('same-ID document reset retires held Prepare and late results cannot tear down a newer editor', async () => {
  const f = fixture(), held = deferred(); f.previewAPI.prepare.mockImplementationOnce(body => held.promise.then(() => f.packet(body)))
  const old = f.open(); await tick(); f.events.dispatchEvent(new Event('nadoc:document-reset'))
  expect(f.editor.active()).toBe(false); expect(await f.open()).toBe(true)
  held.resolve(); expect(await old).toBe(false); expect(f.tool.dispose).not.toHaveBeenCalled()
})
it('tears down immediately on document reset during held Apply and never adopts the old result', async () => {
  const f = fixture(); await f.open(); const held = deferred(); f.previewAPI.apply.mockReturnValue(held.promise)
  const applying = f.callbacks().onApply(); await tick(); const body = f.previewAPI.apply.mock.lastCall[0]
  f.events.dispatchEvent(new Event('nadoc:document-reset'))
  expect(f.tool.dispose).toHaveBeenCalledOnce(); expect(f.preview.dispose).toHaveBeenCalledOnce()
  held.resolve(f.receipt(body)); await applying; expect(f.api.syncDesignResponse).not.toHaveBeenCalled()
})
it('rejects generated/unsupported history definitions without guessing a role', () => {
  expect(isNativeTransformFeature({ feature_type: 'cluster_op', proof_version: 1 })).toBe(true)
  expect(isNativeTransformFeature({ feature_type: 'snapshot', op_kind: 'nucleotide-transform', params: { _proof_version: 1 } })).toBe(true)
  expect(isNativeTransformFeature({ feature_type: 'snapshot', op_kind: 'sweep', params: { _proof_version: 1 } })).toBe(false)
  expect(isNativeTransformFeature({ feature_type: 'snapshot', op_kind: 'nucleotide-transform', params: { _proof_version: 1, _generator: {} } })).toBe(false)
})
it('refuses acquisition while the ordinary live move tool owns the scene', async () => {
  const f = fixture(); f.store.setState({ translateRotateActive: true })
  expect(await f.open()).toBe(false)
  expect(f.previewAPI.prepare).not.toHaveBeenCalled(); expect(f.getPanel).not.toHaveBeenCalled()
})
it('waits for existing comparison views to release before taking the private viewport', async () => {
  const f = fixture(), held = deferred()
  f.events.addEventListener('nadoc:comparison-mode', event => { if (event.detail.mode === 'transform-history') event.detail.waits.push(held.promise) })
  const opening = f.open(); await tick(); expect(f.preview.open).not.toHaveBeenCalled()
  held.resolve(); expect(await opening).toBe(true)
})
it('comparison-mode exit waits for Cancel and refuses to switch while publication is unresolved', async () => {
  const f = fixture(); await f.open(); f.previewAPI.apply.mockRejectedValueOnce(new Error('Disconnected'))
  await f.callbacks().onApply()
  const body = f.previewAPI.apply.mock.lastCall[0]
  f.previewAPI.cancel.mockResolvedValue({ status: 'commit_in_progress', preview_id: body.preview_id, lease_id: lease })
  const waits = []; f.events.dispatchEvent(new CustomEvent('nadoc:comparison-mode', { detail: { mode: 'multi-view', waits } }))
  expect(waits).toHaveLength(1); await expect(Promise.all(waits)).rejects.toThrow(/saved result|publication|commit/i)
  expect(f.editor.active()).toBe(true); expect(f.tool.dispose).not.toHaveBeenCalled()
})
it('document reset during comparison release retires the pending opening', async () => {
  const f = fixture(), held = deferred()
  f.events.addEventListener('nadoc:comparison-mode', event => { if (event.detail.mode === 'transform-history') event.detail.waits.push(held.promise) })
  const opening = f.open(); await tick(); f.events.dispatchEvent(new Event('nadoc:document-reset'))
  held.resolve(); expect(await opening).toBe(false); expect(f.preview.open).not.toHaveBeenCalled()
})
