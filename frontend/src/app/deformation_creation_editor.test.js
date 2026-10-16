// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createDeformationHistoryEditor } from './deformation_history_editor.js'
import * as popupModule from '../ui/bend_twist_popup.js'

const LEASE = '22222222-2222-4222-8222-222222222222'
const OP = '33333333-3333-4333-8333-333333333333'
const targets = [{ kind: 'part_group', id: 'named' }]
const fixtures = []
const tick = async () => { for (let i = 0; i < 24; i++) await Promise.resolve() }
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const control = id => document.getElementById(`def-${id}`)
const input = (id, value, event = 'input') => {
  const node = control(id); node.value = String(value)
  node.dispatchEvent(new Event(event, { bubbles: true }))
}

function mountPopup() {
  document.body.innerHTML = `<div id="deform-panel"><span id="def-panel-title"></span>
    <div id="def-twist-controls"></div><div id="def-bend-controls"></div>
    <input id="def-twist-value"><span id="def-twist-value-label"></span><span id="def-twist-unit"></span>
    <input type="radio" name="hand" id="def-twist-rh"><input type="radio" name="hand" id="def-twist-lh">
    <input type="radio" name="unit" id="def-twist-total-radio"><input type="radio" name="unit" id="def-twist-pernm-radio">
    <input id="def-bend-dir"><input id="def-bend-angle"><input id="def-bend-radius">
    <label id="def-polymer-circle-label"><input type="checkbox" id="def-polymer-circle"></label>
    <div id="def-polymer-count-row"><input id="def-polymer-count" value="3"></div>
    <svg id="def-compass"><line id="def-compass-arm"></line><circle id="def-compass-handle"></circle></svg>
    <input type="checkbox" id="def-preview-check"><button id="def-cancel-btn"></button><button id="def-apply-btn"></button>
    <input id="def-plane-a-bp"><input id="def-plane-b-bp"><span id="def-plane-a-nm"></span><span id="def-plane-b-nm"></span>
    <div id="def-cluster-section"><div id="def-cluster-list"></div><div id="def-cluster-empty-msg"></div></div>
    <button id="def-cluster-all-btn"></button><button id="def-cluster-none-btn"></button>
    <div id="def-bend-hint"></div><div id="def-feasibility"></div></div>`
}

function setup({ holdEvaluate = false, unscoped = false } = {}) {
  mountPopup()
  const group = { id: 'named', name: 'Arm', helix_ids: ['h'], domain_ids: [] }
  const design = { id: 'part', feature_log_cursor: -1, feature_log: [], deformations: [],
    helices: [{ id: 'h', bp_start: 0, length_bp: 101 }],
    strands: [{ id: 's', notes: 'polymerization connector', domains: [{ helix_id: 'h', start_bp: 0, end_bp: 100, direction: 'FORWARD' }] }],
    cluster_transforms: [{ id: 'placement', name: 'Placement', helix_ids: ['h'], domain_ids: [] },
      ...(unscoped ? [{ id: 'second', name: 'Second placement', helix_ids: ['h'], domain_ids: [] }] : [])],
    group_organization: { version: 1, groups: [group, { ...group, id: 'other', name: 'Other' }] },
    forced_ligations: [{ is_periodic_seam: true, three_prime_bp: 0, five_prime_bp: 90 }] }
  const store = createMockStore({ currentDesign: design, currentGeometry: [{ native: true }], currentHelixAxes: { h: { native: true } } })
  const original = JSON.stringify(store.getState()), events = new EventTarget(), held = deferred()
  let revision = 7, phase = 'AWAITING_A', planes = { a: null, b: null }, creation
  const before = { helix_axes: [{ helix_id: 'h', start: [0, 0, 0], end: [0, 0, 34] }] }
  const packet = (body, initial = false) => ({ ...body, mode: 'create', doc_id: 'doc', lease_id: LEASE,
    deformation_id: OP, request_sequence: body.request_sequence ?? 0, remaining_seconds: 60,
    awaiting_parameters: initial, projection_version: 2, before,
    candidate: initial || body.include_geometry === false ? null : { rendered: 'candidate' },
    feasibility: initial ? null : { status: 'ok' },
    selected_scope: { id: OP, affected_helix_ids: ['h'], target_ranges: null },
    control_context: { ...design, selected_operation: null, creation: creation ?? {
      type: body.type, targets: body.targets, cluster_ids: body.cluster_ids },
    capabilities: { change_targets: false, change_clusters: creation?.targets === null,
      native_feasibility: true, polymer_circle_inputs: true } } })
  const previewAPI = { prepare: vi.fn(), prepareCreation: vi.fn(async body => {
    creation = { type: body.type, targets: body.targets, cluster_ids: body.cluster_ids }
    return packet(body, true)
  }), evaluate: vi.fn(async body => holdEvaluate ? held.promise : packet(body)),
  cancel: vi.fn(async () => ({ status: 'cancelled' })), status: vi.fn(),
  apply: vi.fn(async body => ({ ...packet(body), status: 'applied', design_id: 'part', revision: 8 })),
  refreshCommitted: vi.fn(async () => ({ design: { ...design, feature_log: [{ id: 'new', feature_type: 'deformation' }] }, revision: 8 })) }
  const api = { currentRevisionWatermark: () => revision, syncDesignResponse: vi.fn(value => {
    revision = value.revision; store.setState({ currentDesign: value.design }); return Promise.resolve(value)
  }), addDeformation: vi.fn(), updateDeformation: vi.fn(), removeDeformation: vi.fn() }
  const editor = { startToolForCreation: vi.fn(), startToolForHistory: vi.fn(), finishHistoryTool: vi.fn(),
    updateHistoryScope: vi.fn(), getState: () => phase, getPlanes: () => planes,
    repositionPlane: vi.fn((which, bp) => { planes = { ...planes, [which.toLowerCase()]: { bp } } }) }
  const legacy = { onPreview: vi.fn(), onConfirm: vi.fn(), onCancel: vi.fn(), onValidate: vi.fn() }
  popupModule.initBendTwistPopup(legacy)
  const popup = { ...popupModule, openPopup: vi.fn(popupModule.openPopup), showPickingPopup: vi.fn(popupModule.showPickingPopup),
    setHistoryPopupStatus: vi.fn(popupModule.setHistoryPopupStatus) }
  const preview = { open: vi.fn(), replaceCandidate: vi.fn(), show: vi.fn(), dispose: vi.fn() }
  const owner = createDeformationHistoryEditor({ store, api, previewAPI, editor, popup,
    getDocumentId: () => 'doc', showToast: vi.fn(), createPreview: () => preview,
    validateDisplay: value => value, events })
  const f = { owner, store, design, original, api, previewAPI, editor, popup, preview, legacy, events, held, packet,
    async open(type = 'bend', placementHint = null) {
      return owner.openCreation({ type, targets: unscoped ? null : structuredClone(targets), clusterIds: ['placement'], placementHint })
    },
    async place() { phase = 'BOTH'; planes = { a: { bp: 0 }, b: { bp: 100 } }; owner.watchToolState(); await tick() },
    session: () => popup.openPopup.mock.lastCall?.[6],
    unchanged() {
      expect(JSON.stringify(store.getState())).toBe(original)
      expect(api.syncDesignResponse).not.toHaveBeenCalled()
      for (const fn of Object.values(legacy)) expect(fn).not.toHaveBeenCalled()
      for (const name of ['addDeformation', 'updateDeformation', 'removeDeformation']) expect(api[name]).not.toHaveBeenCalled()
    } }
  fixtures.push(f); return f
}

beforeEach(() => { vi.useFakeTimers() })
afterEach(async () => {
  for (const f of fixtures.splice(0)) f.owner.dispose()
  popupModule.closePopup(); await tick(); document.body.innerHTML = ''; vi.useRealTimers(); vi.restoreAllMocks()
})

it.each(['bend', 'twist'])('starts new %s with only private prefix controls and no invented candidate', async type => {
  const f = setup(); expect(await f.open(type)).toBe(true)
  expect(f.previewAPI.prepare).not.toHaveBeenCalled()
  expect(f.previewAPI.prepareCreation).toHaveBeenCalledWith(expect.objectContaining({ mode: 'create', type,
    expected_design_id: 'part', expected_revision: 7, targets, cluster_ids: ['placement'] }), expect.any(Object))
  expect(f.editor.startToolForCreation).toHaveBeenCalledWith({ id: OP, type, targets, cluster_ids: ['placement'] },
    expect.objectContaining({ design: expect.objectContaining({ group_organization: f.design.group_organization }),
      selectedScope: { id: OP, affected_helix_ids: ['h'], target_ranges: null }, onCancel: expect.any(Function) }), null)
  f.owner.watchToolState()
  expect(control('apply-btn').disabled).toBe(true)
  expect(f.previewAPI.evaluate).not.toHaveBeenCalled(); expect(f.previewAPI.apply).not.toHaveBeenCalled()
  f.unchanged()
  await f.owner.cancel(); expect(f.preview.dispose).toHaveBeenCalledOnce(); f.unchanged()
})

it.each([{ kind: 'selection' }, { kind: 'end', helixId: 'h', bp: 100, openSide: 1 }])('forwards the existing plane-placement hint unchanged (%j)', async hint => {
  const f = setup(); await f.open('bend', hint)
  expect(f.editor.startToolForCreation.mock.lastCall[2]).toEqual(hint)
  expect(f.previewAPI.prepareCreation.mock.lastCall[0]).not.toHaveProperty('placementHint')
  f.unchanged()
})

it('keeps Apply disabled until a complete plane/parameter draft has evaluated', async () => {
  const f = setup({ holdEvaluate: true }); await f.open(); await f.place()
  expect(f.previewAPI.evaluate).toHaveBeenCalledOnce()
  const body = f.previewAPI.evaluate.mock.lastCall[0]
  expect(body).toMatchObject({ params: { plane_a_bp: 0, plane_b_bp: 100,
    params: { kind: 'bend', curvature_deg_per_bp: 0, direction_deg: 0 }, cluster_ids: ['placement'] } })
  expect(body).not.toHaveProperty('mode')
  expect(body.params).not.toHaveProperty('targets')
  expect(control('apply-btn').disabled).toBe(true)
  control('apply-btn').click(); expect(f.previewAPI.apply).not.toHaveBeenCalled()
  f.held.resolve(f.packet(body)); await tick()
  expect(control('apply-btn').disabled).toBe(false); f.unchanged()
})

it('retains bend angle/radius/direction, polymer controls, planes and visual-off native feedback', async () => {
  const f = setup(); await f.open(); await f.place()
  input('bend-angle', 90); input('bend-dir', 45); await tick()
  expect(f.previewAPI.evaluate.mock.lastCall[0].params.params).toMatchObject({ kind: 'bend', curvature_deg_per_bp: .9, direction_deg: 45 })
  input('bend-radius', 20); await tick()
  expect(f.previewAPI.evaluate.mock.lastCall[0].params.params.curvature_deg_per_bp).toBeGreaterThan(0)
  expect(control('polymer-circle').disabled).toBe(false)
  control('polymer-circle').checked = true; control('polymer-circle').dispatchEvent(new Event('change', { bubbles: true }))
  input('polymer-count', 4); await tick()
  expect(f.previewAPI.evaluate.mock.lastCall[0].params.params.polymer_circle_count).toBe(4)
  input('plane-a-bp', 2, 'change'); input('plane-b-bp', 98, 'change'); await tick()
  expect(f.editor.repositionPlane.mock.calls.slice(-2)).toEqual([['A', 2], ['B', 98]])
  expect(f.previewAPI.evaluate.mock.lastCall[0].params).toMatchObject({ plane_a_bp: 2, plane_b_bp: 98 })
  control('preview-check').checked = false; control('preview-check').dispatchEvent(new Event('change'))
  await tick(); expect(f.previewAPI.evaluate.mock.lastCall[0].include_geometry).toBe(false)
  expect(f.preview.show).toHaveBeenLastCalledWith('before')
  expect(f.popup.setHistoryPopupStatus.mock.lastCall[0].feasibility).toEqual({ status: 'ok' })
  f.unchanged()
})

it('retains both twist units and handedness through the actual controls', async () => {
  const f = setup(); await f.open('twist'); await f.place()
  input('twist-value', 120); control('twist-lh').checked = true
  control('twist-lh').dispatchEvent(new Event('change', { bubbles: true })); await tick()
  expect(f.previewAPI.evaluate.mock.lastCall[0].params.params).toEqual({ kind: 'twist', total_degrees: -120 })
  control('twist-pernm-radio').checked = true; control('twist-pernm-radio').dispatchEvent(new Event('change', { bubbles: true }))
  input('twist-value', 5); control('twist-rh').checked = true
  control('twist-rh').dispatchEvent(new Event('change', { bubbles: true })); await tick()
  expect(f.previewAPI.evaluate.mock.lastCall[0].params.params).toEqual({ kind: 'twist', degrees_per_nm: 5 })
  f.unchanged()
})

it('shows leased named selection without retargeting or rewriting placement context', async () => {
  const f = setup(); await f.open(); await f.place()
  expect(document.querySelector('#def-current-selection').textContent).toContain('Arm')
  expect(document.querySelectorAll('#def-current-selection input[type=checkbox]')).toHaveLength(0)
  input('bend-angle', 45); await tick()
  expect(f.previewAPI.prepareCreation.mock.lastCall[0].targets).toEqual(targets)
  expect(f.previewAPI.evaluate.mock.lastCall[0].params.cluster_ids).toEqual(['placement'])
  for (const [body] of f.previewAPI.evaluate.mock.calls) {
    expect(body).not.toHaveProperty('mode'); expect(body.params).not.toHaveProperty('targets')
  }
  f.unchanged()
})

it('unscoped creation keeps native placement All/None/individual controls on the same owned lease', async () => {
  const f = setup({ unscoped: true }); await f.open(); await f.place()
  expect(f.previewAPI.prepareCreation.mock.lastCall[0].targets).toBeNull()
  expect(control('cluster-section').style.display).not.toBe('none')
  expect(control('cluster-all-btn').disabled).toBe(false)
  expect(control('cluster-none-btn').disabled).toBe(false)
  control('cluster-none-btn').click(); await tick()
  expect(f.previewAPI.evaluate.mock.lastCall[0].params.cluster_ids).toEqual([])
  control('cluster-all-btn').click(); await tick()
  expect(f.previewAPI.evaluate.mock.lastCall[0].params.cluster_ids).toEqual(['placement', 'second'])
  const first = control('cluster-list').querySelector('input[value="placement"]')
  first.checked = false; first.dispatchEvent(new Event('change')); await tick()
  expect(f.previewAPI.evaluate.mock.lastCall[0].params.cluster_ids).toEqual(['second'])
  expect(f.previewAPI.prepareCreation).toHaveBeenCalledOnce()
  for (const [body] of f.previewAPI.evaluate.mock.calls) {
    expect(body).not.toHaveProperty('mode'); expect(body.params).not.toHaveProperty('targets')
  }
  f.unchanged()
})

it.each(['cancel', 'reset'])('ignores late creation geometry after %s without restoring the old document', async how => {
  const f = setup({ holdEvaluate: true }); await f.open(); await f.place()
  const body = f.previewAPI.evaluate.mock.lastCall[0]
  if (how === 'cancel') await f.owner.cancel()
  else f.events.dispatchEvent(new Event('nadoc:document-reset'))
  f.preview.replaceCandidate.mockClear(); f.editor.updateHistoryScope.mockClear()
  f.held.resolve(f.packet(body)); await tick()
  expect(f.owner.active()).toBe(false)
  expect(f.preview.replaceCandidate).not.toHaveBeenCalled(); expect(f.editor.updateHistoryScope).not.toHaveBeenCalled()
  f.unchanged()
})

it('Cancel before creation preparation completes retires its nonce and never opens the late tool', async () => {
  const f = setup(), held = deferred()
  f.previewAPI.prepareCreation.mockImplementation(() => held.promise)
  const opening = f.open(); await f.owner.cancel()
  const body = f.previewAPI.prepareCreation.mock.lastCall[0]
  expect(f.previewAPI.cancel.mock.calls[0][0].preview_id).toBe(body.preview_id)
  held.resolve(f.packet(body, true)); expect(await opening).toBe(false); await tick()
  expect(f.preview.open).not.toHaveBeenCalled(); expect(f.editor.startToolForCreation).not.toHaveBeenCalled()
  f.unchanged()
})

it('reset during held Prepare permits immediate reopening and ignores the old late packet', async () => {
  const f = setup(), held = deferred()
  f.previewAPI.prepareCreation.mockImplementationOnce(() => held.promise)
  const oldOpening = f.open('bend')
  const oldBody = f.previewAPI.prepareCreation.mock.lastCall[0], oldPacket = f.packet(oldBody, true)
  expect(f.owner.active()).toBe(true)
  f.events.dispatchEvent(new Event('nadoc:document-reset'))
  expect(f.owner.active()).toBe(false)
  expect(await f.open('twist')).toBe(true)
  expect(f.previewAPI.prepareCreation).toHaveBeenCalledTimes(2)
  expect(f.previewAPI.prepareCreation.mock.lastCall[0].preview_id).not.toBe(oldBody.preview_id)
  expect(f.editor.startToolForCreation).toHaveBeenCalledOnce()
  expect(f.editor.startToolForCreation.mock.lastCall[0].type).toBe('twist')
  held.resolve(oldPacket); expect(await oldOpening).toBe(false); await tick()
  expect(f.owner.active()).toBe(true)
  expect(f.preview.open).toHaveBeenCalledOnce()
  expect(f.preview.dispose).not.toHaveBeenCalled()
  expect(f.editor.finishHistoryTool).not.toHaveBeenCalled()
  f.unchanged()
})

it('resolves unknown creation Apply without sending a second append or allowing Cancel to claim rollback', async () => {
  const f = setup(); await f.open(); await f.place()
  f.previewAPI.apply.mockRejectedValueOnce(new Error('Connection lost'))
  expect(await f.session().onApply({})).toBe(false)
  expect(f.owner.active()).toBe(true); expect(control('apply-btn').disabled).toBe(true)
  f.previewAPI.cancel.mockResolvedValue({ status: 'commit_in_progress' })
  expect(await f.session().onCancel()).toBe(false)
  const body = f.previewAPI.apply.mock.lastCall[0]
  f.previewAPI.status.mockResolvedValue({ ...f.packet(body), status: 'applied', design_id: 'part', revision: 8 })
  await f.session().onResolvePublication()
  expect(f.previewAPI.apply).toHaveBeenCalledOnce(); expect(f.api.syncDesignResponse).toHaveBeenCalledOnce()
  expect(f.owner.active()).toBe(false); expect(f.preview.dispose).toHaveBeenCalledOnce()
})

it('a failed creation render blocks Apply and preserves canonical geometry', async () => {
  const f = setup(); await f.open()
  f.preview.replaceCandidate.mockImplementationOnce(() => { throw new Error('Preview rendering refused') })
  await f.place()
  expect(await f.session().onApply({})).toBe(false)
  expect(f.previewAPI.apply).not.toHaveBeenCalled(); f.unchanged()
})
