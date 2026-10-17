import { afterEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { transformPacket } from '../test-helpers/transform_preview.js'
import { createDeformationPreviewEndpoints } from '../api/deformation_preview_endpoints.js'
import { createTransformHistoryEditor, isNativeTransformFeature } from './transform_history_editor.js'

const owners = [], lease = '11111111-1111-4111-8111-111111111111'
const tick = async () => { for (let i = 0; i < 10; i++) await Promise.resolve() }
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function fixture(kind = 'cluster_op', request = null) {
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
  const previewAPI = request ? createDeformationPreviewEndpoints({ request, family: 'transform' })
    : { prepare: vi.fn(async body => packet(body)), evaluate: vi.fn(async body => packet(body)),
    apply: vi.fn(async body => receipt(body)), cancel: vi.fn(async () => ({ status: 'cancelled' })), status: vi.fn(),
    refreshCommitted: vi.fn(async () => ({ design: { ...source }, revision: 8 })) }
  const preview = { open: vi.fn(), replaceCandidate: vi.fn(), show: vi.fn(), dispose: vi.fn() }
  const tool = { open: vi.fn(), update: vi.fn(), setStatus: vi.fn(), dispose: vi.fn(), reset: vi.fn() }
  let callbacks
  const getPanel = vi.fn(() => ({})), createTool = vi.fn(options => { callbacks = options; return tool })
  const showToast = vi.fn()
  const editor = createTransformHistoryEditor({ store, api, previewAPI, events, getDocumentId: () => 'doc', getPanel,
    createPreview: () => preview, createTool, validateDisplay: value => value, showToast })
  owners.push(editor)
  return { editor, source, store, events, api, previewAPI, preview, tool, createTool, getPanel, packet, receipt, showToast,
    callbacks: () => callbacks, open: () => editor.open(source.feature_log[0]) }
}
afterEach(() => { for (const owner of owners.splice(0)) owner.dispose(); vi.useRealTimers(); document.body.innerHTML = '' })
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

const progress = () => document.querySelector('[data-transform-history-progress]')
const progressCancel = () => [...progress().querySelectorAll('button')].find(button => button.textContent === 'Cancel')
it('shows owned preparation status and Cancel before a ready lease or panel exists', async () => {
  const f = fixture(), held = deferred()
  f.previewAPI.prepare.mockImplementationOnce(body => held.promise.then(() => f.packet(body)))
  const opening = f.open(); await tick()
  expect(progress()?.textContent).toMatch(/preparing.*historical/i)
  expect(progress()?.textContent).toMatch(/elapsed/i)
  expect(progress().querySelector('[role="progressbar"]')).toBeNull()
  expect(f.getPanel).not.toHaveBeenCalled(); expect(f.preview.open).not.toHaveBeenCalled()
  progressCancel().click(); await tick()
  expect(f.editor.active()).toBe(false); expect(progress()).toBeNull()
  expect(f.previewAPI.cancel).toHaveBeenCalledWith(expect.objectContaining({ feature_id: 'feature' }), expect.anything())
  held.resolve(); expect(await opening).toBe(false)
  expect(f.api.syncDesignResponse).not.toHaveBeenCalled(); expect(f.preview.open).not.toHaveBeenCalled()
})
it('Escape cancels opening while another comparison view is still releasing', async () => {
  const f = fixture(), held = deferred()
  f.events.addEventListener('nadoc:comparison-mode', event => event.detail.waits.push(held.promise))
  const opening = f.open(); await tick()
  expect(progress()).not.toBeNull()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await tick()
  expect(f.editor.active()).toBe(false); expect(progress()).toBeNull()
  held.resolve(); expect(await opening).toBe(false); expect(f.previewAPI.prepare).not.toHaveBeenCalled()
})
it('reset and a late old Prepare cannot remove the replacement preparation dialog', async () => {
  const f = fixture(), old = deferred(), next = deferred()
  f.previewAPI.prepare.mockImplementationOnce(body => old.promise.then(() => f.packet(body)))
    .mockImplementationOnce(body => next.promise.then(() => f.packet(body)))
  const oldOpening = f.open(); await tick(); const oldDialog = progress()
  f.events.dispatchEvent(new Event('nadoc:document-reset'))
  expect(progress()).toBeNull(); expect(f.editor.active()).toBe(false)
  const nextOpening = f.open(); await tick(); const nextDialog = progress()
  expect(nextDialog).not.toBeNull(); expect(nextDialog).not.toBe(oldDialog)
  old.resolve(); expect(await oldOpening).toBe(false)
  expect(progress()).toBe(nextDialog); expect(f.preview.open).not.toHaveBeenCalled()
  next.resolve(); expect(await nextOpening).toBe(true)
  expect(progress()).toBeNull(); expect(f.tool.dispose).not.toHaveBeenCalled()
})
it('refused preparation removes progress, reports the error and permits a fresh opening', async () => {
  const f = fixture()
  f.previewAPI.prepare.mockRejectedValueOnce(Object.assign(new Error('Historical endpoint is missing'), { status: 422 }))
  expect(await f.open()).toBe(false)
  expect(progress()).toBeNull(); expect(f.editor.active()).toBe(false)
  expect(f.showToast).toHaveBeenCalledWith(expect.stringContaining('Historical endpoint is missing'), 6000)
  expect(f.api.syncDesignResponse).not.toHaveBeenCalled(); expect(await f.open()).toBe(true)
})
it('shows cancellable rebuilding while Apply is held and retains it when commit cannot be cancelled', async () => {
  const f = fixture(); await f.open(); const held = deferred()
  f.previewAPI.apply.mockReturnValue(held.promise)
  const applying = f.callbacks().onApply(); await tick()
  expect(progress()?.textContent).toMatch(/rebuilding/i)
  const body = f.previewAPI.apply.mock.lastCall[0]
  f.previewAPI.cancel.mockResolvedValue({ status: 'commit_in_progress', preview_id: body.preview_id, lease_id: lease })
  progressCancel().click(); await tick()
  expect(progress()?.textContent).toMatch(/not.*confirmed|saved result|commit/i)
  expect(f.editor.active()).toBe(true); expect(f.tool.dispose).not.toHaveBeenCalled()
  held.resolve(f.receipt(body)); expect(await applying).toBe(true)
  expect(progress()).toBeNull(); expect(f.api.syncDesignResponse).toHaveBeenCalledOnce()
})
it('Apply refusal removes progress while keeping the historical draft and its error visible', async () => {
  const f = fixture(); await f.open(); await f.callbacks().onChange({ translation: [3, 2, 1] })
  const held = deferred(); f.previewAPI.apply.mockReturnValue(held.promise)
  const applying = f.callbacks().onApply(); await tick(); expect(progress()).not.toBeNull()
  held.resolve(null); expect(await applying).toBe(false)
  expect(progress()).toBeNull(); expect(f.editor.active()).toBe(true)
  expect(f.tool.setStatus.mock.lastCall[0]).toMatchObject({ publicationUnknown: true })
  expect(f.tool.dispose).not.toHaveBeenCalled(); expect(f.api.syncDesignResponse).not.toHaveBeenCalled()
})
it('dispose releases the opening progress clock and ignores its late request', async () => {
  vi.useFakeTimers()
  const f = fixture(), held = deferred()
  f.previewAPI.prepare.mockImplementationOnce(body => held.promise.then(() => f.packet(body)))
  const opening = f.open(); await tick(); expect(progress()).not.toBeNull()
  expect(vi.getTimerCount()).toBeGreaterThan(0)
  f.editor.dispose(); expect(progress()).toBeNull()
  // JSDOM focus schedules a one-shot selectionchange; flush it without hiding
  // a leaked recurring progress clock or the controller's lease timeout.
  vi.advanceTimersByTime(0); expect(vi.getTimerCount()).toBe(0)
  held.resolve(); expect(await opening).toBe(false); expect(f.getPanel).not.toHaveBeenCalled()
})
it('real endpoint computation polling feeds preparation progress and Cancel aborts a held status read', async () => {
  vi.useFakeTimers()
  const held = deferred(), path = '/design/features/transform-preview'
  let origin, acknowledgement
  const request = vi.fn(async (method, url, body) => {
    expect(method).toBe('POST')
    if (url === path) {
      origin = body
      acknowledgement = { ...body, family: 'transform', command_kind: 'cluster_op', doc_id: 'doc',
        lease_id: lease, request_sequence: 0, status: 'preparing', remaining_seconds: 168,
        computation: { version: 1, operation: 'prepare', request_sequence: 0,
          elapsed_seconds: 12, remaining_seconds: 168 } }
      return acknowledgement
    }
    if (url === `${path}/status`) return held.promise
    if (url === `${path}/cancel`) return { status: 'cancelled', preview_id: body.preview_id }
    throw new Error(`Unexpected transport: ${url}`)
  })
  const f = fixture('cluster_op', request), opening = f.open()
  await tick()
  expect(progress()?.textContent).toContain('12.0s')
  expect(f.tool.open).not.toHaveBeenCalled(); expect(f.getPanel).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(500)
  const statusCall = request.mock.calls.find(call => call[1] === `${path}/status`)
  expect(statusCall).toBeDefined()
  expect(statusCall[2]).toEqual({ ...origin, lease_id: lease })
  expect(statusCall[3]).toMatchObject({ docId: 'doc', suppressBusy: true, protectedRetry: false })
  progressCancel().click()
  expect(await opening).toBe(false); await tick()
  expect(statusCall[3].signal.aborted).toBe(true)
  expect(progress()).toBeNull(); expect(f.editor.active()).toBe(false)
  const cancels = request.mock.calls.filter(call => call[1] === `${path}/cancel`)
  expect(cancels).toHaveLength(1)
  expect(cancels[0][2]).toEqual({ ...origin, lease_id: lease })
  held.resolve({ ...acknowledgement, status: 'ready', remaining_seconds: 60, result: f.packet(origin) })
  await tick(); vi.advanceTimersByTime(0)
  expect(f.tool.open).not.toHaveBeenCalled(); expect(f.api.syncDesignResponse).not.toHaveBeenCalled()
  expect(f.store.getState().currentDesign).toBe(f.source)
  expect(vi.getTimerCount()).toBe(0)
})
