import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const modulePath = './deformation_history_controller.js'
const PREVIEW = '11111111-1111-4111-8111-111111111111'
const LEASE = '22222222-2222-4222-8222-222222222222'
const operation = { id: 'operation', type: 'bend', plane_a_bp: 4, plane_b_bp: 32,
  affected_helix_ids: ['helix'], cluster_ids: [], params: { kind: 'bend', curvature_deg_per_bp: .25, direction_deg: 0 } }
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }
const patch = curvature => ({ params: { kind: 'bend', curvature_deg_per_bp: curvature, direction_deg: 0 } })

function packet(body, extra = {}) {
  return { ...body, doc_id: 'doc', lease_id: LEASE, deformation_id: 'operation',
    request_sequence: body.request_sequence ?? 0, remaining_seconds: 60,
    projection_version: 2, stage: 'feature', source_equivalence_checked: false,
    downstream_evaluated: false, physical_validity: false,
    before: { pane: 'before' }, candidate: { pane: 'candidate' },
    control_context: { selected_operation: structuredClone(operation) }, feasibility: { status: 'ok' }, ...extra }
}

const fixtures = []
async function fixture(overrides = {}, options = {}) {
  let context = { docId: 'doc', designId: 'part', revision: 7, loadoutId: null, editable: true, cursor: -1, subCursor: null }
  let listener = () => {}
  const api = {
    prepare: vi.fn(async body => packet(body)), evaluate: vi.fn(async body => packet(body)),
    cancel: vi.fn(async () => ({ status: 'cancelled' })),
    apply: vi.fn(async body => ({ ...packet(body), status: 'applied', design_id: 'part', revision: 8 })),
    status: vi.fn(), refreshCommitted: vi.fn(async () => ({ design: { id: 'part' }, revision: 8 })),
    ...overrides,
  }
  const validateDisplay = vi.fn(value => value), applyPublished = vi.fn()
  const { createDeformationHistoryController } = await import(modulePath)
  const events = new EventTarget()
  const controller = createDeformationHistoryController({ api, getContext: () => context,
    subscribeContext: callback => { listener = callback; return vi.fn() },
    validateDisplay, applyPublished, events, uuid: () => PREVIEW, now: () => Date.now(), ...options })
  const value = { controller, api, validateDisplay, applyPublished, events,
    setContext(next, notify = true) { context = { ...context, ...next }; if (notify) listener() },
    context: () => context }
  fixtures.push(value)
  return value
}

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(1000) })
afterEach(async () => {
  for (const { controller } of fixtures.splice(0)) controller.dispose()
  await tick(); vi.useRealTimers()
})

describe('isolated deformation history controller', () => {
  it('binds a stable feature and known-before-request nonce without canonical writes', async () => {
    const f = await fixture()
    await f.controller.open('feature')
    expect(f.api.prepare).toHaveBeenCalledWith({ preview_id: PREVIEW, expected_design_id: 'part', expected_revision: 7, feature_id: 'feature' },
      expect.objectContaining({ context: expect.objectContaining({ docId: 'doc' }), signal: expect.any(AbortSignal) }))
    expect(f.controller.getState()).toMatchObject({ open: true, featureId: 'feature', deformationId: 'operation', busy: null })
    expect(f.validateDisplay).toHaveBeenCalledOnce()
    expect(f.api.apply).not.toHaveBeenCalled(); expect(f.applyPublished).not.toHaveBeenCalled()
  })

  it('coalesces slider requests to one active evaluation and the latest pending draft', async () => {
    const held = deferred(), f = await fixture({ evaluate: vi.fn().mockImplementationOnce(() => held.promise).mockImplementation(async body => packet(body)) })
    await f.controller.open('feature')
    const first = f.controller.update(patch(.5)), skipped = f.controller.update(patch(.75)), latest = f.controller.update(patch(1))
    expect(f.api.evaluate).toHaveBeenCalledTimes(1)
    held.resolve(packet(f.api.evaluate.mock.calls[0][0], { candidate: { pane: 'obsolete' } }))
    await Promise.all([first, skipped, latest])
    expect(f.api.evaluate).toHaveBeenCalledTimes(2)
    expect(f.api.evaluate.mock.calls[1][0].params.params.curvature_deg_per_bp).toBe(1)
    expect(f.api.evaluate.mock.calls[1][0].request_sequence).toBe(2)
    expect(f.controller.getState().projection.candidate.pane).not.toBe('obsolete')
  })

  it('Apply drains the latest draft once, then privately refreshes before one publication sync', async () => {
    const held = deferred(), f = await fixture({ evaluate: vi.fn().mockImplementationOnce(() => held.promise).mockImplementation(async body => packet(body)) })
    await f.controller.open('feature')
    const first = f.controller.update(patch(.5)), latest = f.controller.update(patch(.75))
    const applied = f.controller.apply()
    expect(f.api.apply).not.toHaveBeenCalled()
    held.resolve(packet(f.api.evaluate.mock.calls[0][0]))
    await Promise.all([first, latest, applied])
    expect(f.api.apply).toHaveBeenCalledTimes(1)
    expect(f.api.apply.mock.calls[0][0]).toMatchObject({ request_sequence: 3, params: patch(.75) })
    expect(f.api.refreshCommitted).toHaveBeenCalledOnce()
    expect(f.applyPublished).toHaveBeenCalledWith({ design: { id: 'part' }, revision: 8 }, expect.objectContaining({ docId: 'doc', revision: 7 }),
      expect.objectContaining({ status: 'applied', revision: 8 }))
    expect(f.controller.getState().open).toBe(false)
  })

  it('accepts the actual small Apply receipt using only the retained origin binding', async () => {
    const f = await fixture({ apply: vi.fn(async body => ({ status: 'applied', preview_id: body.preview_id,
      lease_id: body.lease_id, design_id: 'part', revision: 8, feature_id: body.feature_id,
      doc_id: 'doc', request_sequence: body.request_sequence, validation: { passed: true } })) })
    await f.controller.open('feature'); await f.controller.apply()
    expect(f.applyPublished).toHaveBeenCalledOnce()
    expect(f.controller.getState().committed).toMatchObject({ expected_design_id: 'part', expected_revision: 7,
      deformation_id: 'operation', revision: 8 })
    expect(f.controller.getState().committed).not.toHaveProperty('validation')
  })

  it('Cancel returning the small applied receipt resolves a lost publication without recommitting', async () => {
    const f = await fixture({ apply: vi.fn().mockRejectedValue(Object.assign(new Error('Lost reply'), { status: 0 })) })
    await f.controller.open('feature'); await f.controller.apply()
    const body = f.api.apply.mock.calls[0][0]
    f.api.cancel.mockResolvedValue({ status: 'applied', preview_id: PREVIEW, lease_id: LEASE,
      design_id: 'part', revision: 8, feature_id: 'feature', doc_id: 'doc', request_sequence: body.request_sequence })
    await f.controller.cancel()
    expect(f.api.apply).toHaveBeenCalledOnce(); expect(f.applyPublished).toHaveBeenCalledOnce()
  })

  it('a known Apply refusal retains fields and permits an explicit later retry', async () => {
    const f = await fixture({ apply: vi.fn().mockRejectedValueOnce(Object.assign(new Error('Missing upstream reference'), { status: 422 }))
      .mockImplementation(async body => ({ ...packet(body), status: 'applied', design_id: 'part', revision: 8 })) })
    await f.controller.open('feature'); await f.controller.update(patch(.75)); await f.controller.apply()
    expect(f.controller.getState()).toMatchObject({ open: true, draft: patch(.75), error: expect.any(Error), publicationUnknown: false })
    expect(f.applyPublished).not.toHaveBeenCalled()
    await f.controller.apply()
    expect(f.api.apply).toHaveBeenCalledTimes(2)
  })

  it('does not Apply after the latest evaluation failed or transparently retry a busy operation', async () => {
    const f = await fixture({ evaluate: vi.fn().mockRejectedValue(Object.assign(new Error('Preview busy'), { status: 429, code: 'preview_busy' })) })
    await f.controller.open('feature'); await f.controller.update(patch(.5)); await f.controller.apply()
    expect(f.api.apply).not.toHaveBeenCalled()
    expect(f.api.evaluate).toHaveBeenCalledOnce()
    expect(f.controller.getState()).toMatchObject({ open: true, draft: patch(.5), error: expect.any(Error) })
  })

  it('keeps a published receipt when display refresh fails and never commits it twice', async () => {
    const f = await fixture({ refreshCommitted: vi.fn().mockRejectedValueOnce(new Error('Read failed'))
      .mockResolvedValue({ design: { id: 'part' }, revision: 8 }) })
    await f.controller.open('feature'); await f.controller.apply()
    expect(f.controller.getState()).toMatchObject({ open: true, refreshNeeded: true, committed: expect.objectContaining({ revision: 8 }) })
    await f.controller.apply()
    expect(f.api.apply).toHaveBeenCalledOnce()
    await f.controller.refreshCommitted()
    expect(f.applyPublished).toHaveBeenCalledOnce()
  })

  it('resolves a lost Apply response through status without recommitting', async () => {
    const f = await fixture({ apply: vi.fn().mockRejectedValue(Object.assign(new Error('Connection lost'), { status: 0 })) })
    await f.controller.open('feature'); await f.controller.apply()
    expect(f.controller.getState()).toMatchObject({ open: true, publicationUnknown: true, draft: expect.any(Object) })
    await f.controller.apply()
    expect(f.api.apply).toHaveBeenCalledOnce()
    const body = f.api.apply.mock.calls[0][0]
    f.api.status.mockResolvedValue({ ...packet(body), status: 'applied', design_id: 'part', revision: 8 })
    await f.controller.resolvePublication()
    expect(f.api.apply).toHaveBeenCalledOnce(); expect(f.applyPublished).toHaveBeenCalledOnce()
    expect(f.api.status).toHaveBeenCalledWith(expect.objectContaining({ preview_id: PREVIEW, lease_id: LEASE }), expect.any(Object))
  })

  it('cancel while Open is pending uses its nonce and cleans a late lease without displaying it', async () => {
    const held = deferred(), f = await fixture({ prepare: vi.fn(() => held.promise) })
    const opening = f.controller.open('feature')
    await f.controller.cancel()
    expect(f.api.cancel.mock.calls[0][0]).toMatchObject({ preview_id: PREVIEW, feature_id: 'feature' })
    expect(f.api.cancel.mock.calls[0][0]).not.toHaveProperty('lease_id')
    held.resolve(packet(f.api.prepare.mock.calls[0][0]))
    await opening; await tick()
    expect(f.controller.getState()).toMatchObject({ open: false, projection: null })
    expect(f.api.cancel.mock.calls.some(([body]) => body.lease_id === LEASE)).toBe(true)
    expect(f.applyPublished).not.toHaveBeenCalled()
  })

  it.each([{ docId: 'elsewhere' }, { designId: 'replacement' }, { revision: 8 }, { loadoutId: 'physical' }])('rejects late geometry after context changes (%j)', async change => {
    const held = deferred(), f = await fixture({ evaluate: vi.fn(() => held.promise) })
    await f.controller.open('feature')
    const pending = f.controller.update(patch(.5))
    f.setContext(change)
    held.resolve(packet(f.api.evaluate.mock.calls[0][0]))
    await pending
    expect(f.controller.getState()).toMatchObject({ open: false, projection: null })
    expect(f.api.cancel.mock.calls.at(-1)[1].context.docId).toBe('doc')
    expect(f.applyPublished).not.toHaveBeenCalled()
  })

  it('document reset invalidates even an identical document ID/revision', async () => {
    const f = await fixture()
    await f.controller.open('feature')
    f.events.dispatchEvent(new Event('nadoc:document-reset'))
    expect(f.controller.getState()).toMatchObject({ open: false, projection: null })
    expect(f.api.cancel).toHaveBeenCalledOnce()
  })

  it.each(['preview_id', 'lease_id', 'expected_design_id', 'expected_revision', 'feature_id', 'deformation_id', 'request_sequence', 'doc_id'])('rejects a mismatched %s response without replacing the last display', async field => {
    const f = await fixture()
    await f.controller.open('feature')
    const before = f.controller.getState().projection
    f.api.evaluate.mockImplementation(async body => packet(body, { [field]: typeof body[field] === 'number' ? 999 : 'foreign' }))
    await f.controller.update(patch(.5))
    expect(f.controller.getState().projection).toBe(before)
    expect(f.controller.getState().error).toBeInstanceOf(Error)
  })

  it('validates complete display before accepting it and exposes expiry without further work', async () => {
    const f = await fixture()
    await f.controller.open('feature')
    f.validateDisplay.mockImplementationOnce(() => { throw new Error('Incomplete native axes') })
    await f.controller.update(patch(.5))
    expect(f.controller.getState().error.message).toContain('Incomplete')
    await vi.advanceTimersByTimeAsync(60001)
    expect(f.controller.getState()).toMatchObject({ open: true, expired: true, projection: null })
    await f.controller.update(patch(.75)); await f.controller.apply()
    expect(f.api.evaluate).toHaveBeenCalledOnce(); expect(f.api.apply).not.toHaveBeenCalled()
  })

  it('supports feedback with visual preview off without silently changing that draft at Apply', async () => {
    const f = await fixture()
    await f.controller.open('feature'); await f.controller.update(patch(.75), { includeGeometry: false })
    expect(f.api.evaluate.mock.calls[0][0].include_geometry).toBe(false)
    await f.controller.apply()
    expect(f.api.apply.mock.calls[0][0].params.params.curvature_deg_per_bp).toBe(.75)
    expect(f.api.apply.mock.calls[0][0]).not.toHaveProperty('include_geometry')
  })

  it('caller and snapshot input mutations cannot change the eventual Apply draft', async () => {
    const f = await fixture()
    await f.controller.open('feature')
    const change = patch(.5), pending = f.controller.update(change)
    change.params.curvature_deg_per_bp = 99
    await pending
    f.controller.getState().draft.params.curvature_deg_per_bp = 77
    await f.controller.apply()
    expect(f.api.apply.mock.calls[0][0].params.params.curvature_deg_per_bp).toBe(.5)
  })

  it('rechecks local context after private publication reads before syncing', async () => {
    const held = deferred(), f = await fixture({ refreshCommitted: vi.fn(() => held.promise) })
    await f.controller.open('feature')
    const applying = f.controller.apply()
    await tick(); expect(f.api.refreshCommitted).toHaveBeenCalledOnce()
    f.setContext({ docId: 'other' }, false)
    held.resolve({ design: { id: 'part' }, revision: 8 })
    await applying
    expect(f.applyPublished).not.toHaveBeenCalled()
  })

  it('Cancel confirmation during private Apply refresh preserves the receipt and adopts once', async () => {
    const reads = deferred(), f = await fixture({ refreshCommitted: vi.fn(() => reads.promise) })
    await f.controller.open('feature')
    const applying = f.controller.apply(); await tick()
    const receipt = f.controller.getState().committed
    expect(receipt).toMatchObject({ status: 'applied', revision: 8 })
    f.api.cancel.mockResolvedValue({ ...receipt })
    await f.controller.cancel()
    reads.resolve({ design: { id: 'part' }, revision: 8 })
    await applying
    expect(f.applyPublished).toHaveBeenCalledOnce()
    expect(f.controller.getState()).toMatchObject({ open: false, refreshNeeded: false, publicationUnknown: false })
  })

  it('refresh and Cancel after completed display adoption cannot adopt a publication again', async () => {
    const f = await fixture()
    await f.controller.open('feature'); await f.controller.apply()
    const receipt = f.controller.getState().committed
    f.api.cancel.mockResolvedValue({ ...receipt })
    await f.controller.refreshCommitted(); await f.controller.cancel()
    expect(f.api.refreshCommitted).toHaveBeenCalledOnce()
    expect(f.applyPublished).toHaveBeenCalledOnce()
    expect(f.api.apply).toHaveBeenCalledOnce()
  })

  it('a confirmed Cancel-applied receipt survives a later failed original Apply response', async () => {
    const held = deferred(), f = await fixture({ apply: vi.fn(() => held.promise) })
    await f.controller.open('feature')
    const applying = f.controller.apply(); await tick()
    const body = f.api.apply.mock.calls[0][0]
    f.api.cancel.mockResolvedValue({ status: 'applied', preview_id: PREVIEW, lease_id: LEASE,
      design_id: 'part', revision: 8, feature_id: 'feature', doc_id: 'doc', request_sequence: body.request_sequence })
    await f.controller.cancel()
    held.reject(Object.assign(new Error('Original response lost'), { status: 0 }))
    await applying
    expect(f.controller.getState()).toMatchObject({ publicationUnknown: false, refreshNeeded: true,
      committed: expect.objectContaining({ status: 'applied', revision: 8 }) })
    await f.controller.refreshCommitted()
    expect(f.api.apply).toHaveBeenCalledOnce(); expect(f.applyPublished).toHaveBeenCalledOnce()
  })

  it('retains the editor if Cancel reports publication is already committing', async () => {
    const held = deferred(), f = await fixture({ apply: vi.fn(() => held.promise), cancel: vi.fn(async () => ({ status: 'commit_in_progress' })) })
    await f.controller.open('feature')
    const applying = f.controller.apply(); await tick()
    await f.controller.cancel()
    expect(f.controller.getState().open).toBe(true)
    held.resolve({ ...packet(f.api.apply.mock.calls[0][0]), status: 'applied', design_id: 'part', revision: 8 })
    await applying
    expect(f.applyPublished).toHaveBeenCalledOnce()
  })
})

const creation = { type: 'bend', targets: [{ kind: 'strand', id: 'strand' }], clusterIds: [] }
const completeCreation = { plane_a_bp: 4, plane_b_bp: 32, params: { kind: 'bend', curvature_deg_per_bp: .25, direction_deg: 0 }, cluster_ids: [] }
const createPacket = (body, ready = false) => packet(body, { mode: 'create', awaiting_parameters: !ready,
  candidate: ready ? { pane: 'candidate' } : null, feasibility: ready ? { status: 'ok' } : null,
  control_context: { selected_operation: null, creation: { type: body.type, targets: body.targets, cluster_ids: body.cluster_ids } } })

it('prepares a new identity without a candidate and cannot Apply before a complete evaluated draft', async () => {
  const f = await fixture({ prepareCreation: vi.fn(async body => createPacket(body)), evaluate: vi.fn(async body => createPacket(body, true)) })
  await f.controller.openCreation(creation)
  expect(f.api.prepare).not.toHaveBeenCalled()
  expect(f.api.prepareCreation.mock.lastCall[0]).toEqual({ mode: 'create', preview_id: PREVIEW, feature_id: PREVIEW,
    expected_design_id: 'part', expected_revision: 7, type: 'bend', targets: creation.targets, cluster_ids: [] })
  expect(f.controller.getState()).toMatchObject({ mode: 'create', awaitingParameters: true, projection: { candidate: null } })
  await f.controller.apply(); expect(f.api.apply).not.toHaveBeenCalled()
  await f.controller.update(completeCreation, { includeGeometry: false })
  expect(f.api.evaluate.mock.lastCall[0]).toMatchObject({ params: completeCreation, include_geometry: false })
  expect(f.controller.getState().awaitingParameters).toBe(false)
  await f.controller.apply()
  expect(f.api.apply).toHaveBeenCalledOnce(); expect(f.applyPublished).toHaveBeenCalledOnce()
})

it('cancels a create nonce before Prepare completes and discards its late owned result', async () => {
  const held = deferred(), f = await fixture({ prepareCreation: vi.fn(() => held.promise) })
  const opening = f.controller.openCreation(creation)
  await f.controller.cancel()
  held.resolve(createPacket(f.api.prepareCreation.mock.lastCall[0])); await opening
  expect(f.controller.getState().open).toBe(false)
  expect(f.api.cancel).toHaveBeenCalledWith(expect.objectContaining({ preview_id: PREVIEW, feature_id: PREVIEW }), expect.any(Object))
  expect(f.api.apply).not.toHaveBeenCalled(); expect(f.applyPublished).not.toHaveBeenCalled()
})

it('keeps create mode separate from edit responses and leaves failed initial evaluation unapplied', async () => {
  const f = await fixture({ prepareCreation: vi.fn(async body => createPacket(body)), evaluate: vi.fn(async body => packet(body)) })
  await f.controller.openCreation(creation); await f.controller.update(completeCreation)
  expect(f.controller.getState().error).toBeTruthy()
  await f.controller.apply(); expect(f.api.apply).not.toHaveBeenCalled()
})

const TRANSFORMS = ['cluster_op', 'nucleotide-transform', 'nucleotide-transform-batch', 'nucleotide-transform-delete', 'placement-poses']
const transformPacket = (body, kind = 'cluster_op', extra = {}) => ({ ...body,
  doc_id: 'doc', lease_id: LEASE, request_sequence: body.request_sequence ?? 0, remaining_seconds: 60,
  family: 'transform', command_kind: kind, evaluated_command_kind: kind, projection_version: 1, stage: 'feature',
  source_equivalence_checked: false, downstream_evaluated: false, physical_validity: false,
  before: { pane: 'before' }, candidate: body.include_geometry === false ? null : { pane: 'candidate' },
  control_context: { inputs: { translation: [0, 0, 0] } }, control_state: { inputs: body.params ?? {} }, ...extra })
const transformReceipt = (body, kind = 'cluster_op', extra = {}) => ({
  ...Object.fromEntries(['preview_id', 'expected_design_id', 'expected_revision', 'feature_id', 'lease_id', 'request_sequence']
    .map(key => [key, body[key]])), status: 'applied', family: 'transform', command_kind: kind,
  doc_id: 'doc', design_id: 'part', revision: 8, ...extra })
async function transformFixture(kind = 'cluster_op', overrides = {}, options = {}) {
  return fixture({ prepare: vi.fn(async body => transformPacket(body, kind)),
    evaluate: vi.fn(async body => transformPacket(body, kind)),
    apply: vi.fn(async body => transformReceipt(body, kind)), ...overrides }, { family: 'transform', ...options })
}

describe('declared transform editor lifecycle', () => {
  it.each(TRANSFORMS)('binds %s and adopts one exact scalar receipt without a deformation ID', async kind => {
    const f = await transformFixture(kind)
    expect(await f.controller.open('feature')).toBeTruthy()
    expect(f.controller.getState()).toMatchObject({ open: true, featureId: 'feature', commandKind: kind })
    expect(f.controller.getState()).not.toHaveProperty('deformationId')
    const draft = kind === 'nucleotide-transform-delete' ? {} : { translation: [1, 2, 3] }
    await f.controller.update(draft, { includeGeometry: false })
    expect(f.controller.getState().projection.candidate).toBeNull()
    await f.controller.apply()
    expect(f.api.apply.mock.lastCall[0]).toMatchObject({ feature_id: 'feature', params: draft })
    expect(f.api.apply.mock.lastCall[0]).not.toHaveProperty('deformation_id')
    expect(f.applyPublished).toHaveBeenCalledOnce()
    expect(f.controller.getState().committed).toMatchObject({ family: 'transform', command_kind: kind, feature_id: 'feature' })
    expect(f.controller.getState().committed).not.toHaveProperty('deformation_id')
    await f.controller.apply(); await f.controller.refreshCommitted()
    expect(f.api.apply).toHaveBeenCalledOnce(); expect(f.applyPublished).toHaveBeenCalledOnce()
  })

  it.each([['family', 'sweep'], ['command_kind', 'deformation'], ['command_kind', null],
    ['deformation_id', 'fabricated']])('refuses malformed Prepare identity %s', async (field, value) => {
    const f = await transformFixture('cluster_op', { prepare: vi.fn(async body => transformPacket(body, 'cluster_op', { [field]: value })) })
    expect(await f.controller.open('feature')).toBeNull()
    expect(f.controller.getState().projection).toBeNull()
    await f.controller.apply(); expect(f.api.apply).not.toHaveBeenCalled()
  })

  it('does not auto-select a transform contract from a response in the default controller', async () => {
    const f = await fixture({ prepare: vi.fn(async body => transformPacket(body)) })
    expect(await f.controller.open('feature')).toBeNull()
    expect(f.controller.getState().projection).toBeNull()
  })

  it('rejects unknown declared families and transform creation before a request', async () => {
    const { createDeformationHistoryController } = await import(modulePath)
    expect(() => createDeformationHistoryController({ api: {}, getContext: () => ({}),
      validateDisplay: () => {}, applyPublished: () => {}, family: 'untrusted' })).toThrow()
    const f = await transformFixture('cluster_op', { prepareCreation: vi.fn() })
    expect(await f.controller.openCreation(creation)).toBeNull()
    expect(f.api.prepareCreation).not.toHaveBeenCalled(); expect(f.api.prepare).not.toHaveBeenCalled()
  })

  it('requires the bound command kind on every evaluation without erasing the accepted pane', async () => {
    const f = await transformFixture()
    await f.controller.open('feature')
    const before = f.controller.getState().projection
    f.api.evaluate.mockImplementation(async body => transformPacket(body, 'nucleotide-transform'))
    await f.controller.update({ translation: [1, 2, 3] })
    expect(f.controller.getState().projection).toBe(before)
    expect(f.controller.getState().error).toBeTruthy()
    await f.controller.apply(); expect(f.api.apply).not.toHaveBeenCalled()
  })

  it.each(['apply', 'status', 'cancel'])('refuses a foreign-kind %s receipt and can resolve the original publication', async method => {
    const f = await transformFixture('cluster_op', { apply: vi.fn().mockRejectedValue(Object.assign(new Error('Lost'), { status: 0 })) })
    await f.controller.open('feature')
    if (method === 'apply') f.api.apply.mockImplementation(async body => transformReceipt(body, 'nucleotide-transform'))
    await f.controller.apply()
    const body = f.api.apply.mock.lastCall[0]
    if (method !== 'apply') {
      f.api[method].mockResolvedValue(transformReceipt(body, 'nucleotide-transform'))
      await (method === 'status' ? f.controller.resolvePublication() : f.controller.cancel())
    }
    expect(f.applyPublished).not.toHaveBeenCalled()
    expect(f.controller.getState()).toMatchObject({ open: true, committed: null, publicationUnknown: true })
    f.api.status.mockResolvedValue(transformReceipt(body))
    await f.controller.resolvePublication()
    expect(f.api.apply).toHaveBeenCalledOnce(); expect(f.applyPublished).toHaveBeenCalledOnce()
  })

  it.each(['family', 'command_kind', 'expected_design_id', 'expected_revision'])('does not enrich missing transform Apply %s', async field => {
    const f = await transformFixture('cluster_op', { apply: vi.fn(async body => {
      const value = transformReceipt(body); delete value[field]; return value
    }) })
    await f.controller.open('feature'); await f.controller.apply()
    expect(f.applyPublished).not.toHaveBeenCalled()
    expect(f.controller.getState()).toMatchObject({ committed: null, publicationUnknown: true })
  })

  it('cancels pending Prepare by nonce and ignores its late owned result', async () => {
    const held = deferred(), f = await transformFixture('cluster_op', { prepare: vi.fn(() => held.promise) })
    const opening = f.controller.open('feature')
    await f.controller.cancel()
    expect(f.api.cancel.mock.calls[0][0]).toEqual({ preview_id: PREVIEW, expected_design_id: 'part', expected_revision: 7, feature_id: 'feature' })
    held.resolve(transformPacket(f.api.prepare.mock.lastCall[0])); await opening
    expect(f.controller.getState()).toMatchObject({ open: false, projection: null })
    expect(f.api.cancel.mock.calls.some(([body]) => body.lease_id === LEASE)).toBe(true)
  })

  it('retains confirmed publication after a racing original transport failure', async () => {
    const held = deferred(), f = await transformFixture('nucleotide-transform-delete', { apply: vi.fn(() => held.promise) })
    await f.controller.open('feature')
    const applying = f.controller.apply(); await tick()
    const body = f.api.apply.mock.lastCall[0]
    f.api.cancel.mockResolvedValue(transformReceipt(body, 'nucleotide-transform-delete'))
    await f.controller.cancel()
    held.reject(Object.assign(new Error('Original response lost'), { status: 0 })); await applying
    expect(f.controller.getState()).toMatchObject({ publicationUnknown: false, refreshNeeded: true,
      committed: expect.objectContaining({ command_kind: 'nucleotide-transform-delete' }) })
    await f.controller.refreshCommitted()
    expect(f.api.apply).toHaveBeenCalledOnce(); expect(f.applyPublished).toHaveBeenCalledOnce()
  })

  it('does not replace confirmed publication with uncertainty after a conflicting late Apply reply', async () => {
    const held = deferred(), f = await transformFixture('cluster_op', { apply: vi.fn(() => held.promise) })
    await f.controller.open('feature')
    const applying = f.controller.apply(); await tick()
    const body = f.api.apply.mock.lastCall[0]
    f.api.cancel.mockResolvedValue(transformReceipt(body))
    await f.controller.cancel()
    const confirmed = f.controller.getState().committed
    held.resolve(transformReceipt(body, 'nucleotide-transform')); await applying
    expect(f.controller.getState()).toMatchObject({ committed: confirmed, publicationUnknown: false, refreshNeeded: true })
    expect(f.applyPublished).not.toHaveBeenCalled()
    await f.controller.refreshCommitted()
    expect(f.api.apply).toHaveBeenCalledOnce(); expect(f.applyPublished).toHaveBeenCalledOnce()
  })

  it('ignores an old Apply after same-document reset and a new feature opening', async () => {
    const held = deferred(), f = await transformFixture('cluster_op', { apply: vi.fn(() => held.promise) })
    await f.controller.open('old-feature')
    const applying = f.controller.apply(); await tick()
    const body = f.api.apply.mock.lastCall[0]
    f.events.dispatchEvent(new Event('nadoc:document-reset'))
    f.api.prepare.mockImplementation(async request => transformPacket(request, 'nucleotide-transform'))
    await f.controller.open('new-feature')
    held.resolve(transformReceipt(body)); await applying
    expect(f.controller.getState()).toMatchObject({ open: true, featureId: 'new-feature', commandKind: 'nucleotide-transform', committed: null })
    expect(f.applyPublished).not.toHaveBeenCalled()
  })

  it('does not adopt after the source changes during private publication reads', async () => {
    const held = deferred(), f = await transformFixture('cluster_op', { refreshCommitted: vi.fn(() => held.promise) })
    await f.controller.open('feature')
    const applying = f.controller.apply(); await tick()
    f.setContext({ revision: 9 }, false)
    held.resolve({ design: { id: 'part' }, revision: 8 }); await applying
    expect(f.applyPublished).not.toHaveBeenCalled()
  })

  it('expires an idle transform lease without another native request', async () => {
    const f = await transformFixture()
    await f.controller.open('feature')
    await vi.advanceTimersByTimeAsync(60001)
    expect(f.controller.getState()).toMatchObject({ open: true, expired: true, projection: null })
    await f.controller.update({ translation: [1, 2, 3] }); await f.controller.apply()
    expect(f.api.evaluate).not.toHaveBeenCalled(); expect(f.api.apply).not.toHaveBeenCalled()
  })

  it('keeps original lease identity when an explicit draft upgrades the evaluated command', async () => {
    const f = await transformFixture('cluster_op', { evaluate: vi.fn(async body =>
      transformPacket(body, 'cluster_op', { evaluated_command_kind: 'placement-poses' })) })
    await f.controller.open('feature')
    const draft = { upgrade_to: 'placement-poses-v1', expected_definition_sha256: 'a'.repeat(64),
      definition: { primary_cluster_id: 'primary', poses: [] } }
    await f.controller.update(draft)
    expect(f.controller.getState()).toMatchObject({ commandKind: 'cluster_op',
      projection: { command_kind: 'cluster_op', evaluated_command_kind: 'placement-poses' } })
    await f.controller.apply()
    expect(f.api.apply.mock.lastCall[0].params).toEqual(draft)
    expect(f.controller.getState().committed.command_kind).toBe('cluster_op')
  })

  it.each(['cancelled', 'commit_in_progress'])('refuses a foreign %s acknowledgment during an unresolved Apply', async status => {
    const held = deferred(), f = await transformFixture('cluster_op', { apply: vi.fn(() => held.promise) })
    await f.controller.open('feature')
    const applying = f.controller.apply(); await tick()
    const body = f.api.apply.mock.lastCall[0]
    f.api.cancel.mockResolvedValue({ status, preview_id: 'foreign', lease_id: LEASE })
    await f.controller.cancel()
    expect(f.controller.getState()).toMatchObject({ open: true, error: expect.any(Error), committed: null })
    f.api.cancel.mockResolvedValue({ status: 'commit_in_progress', preview_id: PREVIEW, lease_id: LEASE })
    expect(await f.controller.cancel()).toMatchObject({ status: 'commit_in_progress' })
    held.resolve(transformReceipt(body)); await applying
    expect(f.applyPublished).toHaveBeenCalledOnce()
  })
})

it('Reset replaces an accumulated transform upgrade and waits for its independent evaluation before Apply', async () => {
  const f = await transformFixture('cluster_op', { evaluate: vi.fn(async body => transformPacket(body, 'cluster_op', {
    evaluated_command_kind: body.params.upgrade_to === 'placement-poses-v1' ? 'placement-poses' : 'cluster_op',
  })) })
  await f.controller.open('feature')
  expect(await f.controller.update({ upgrade_to: 'placement-poses-v1', expected_definition_sha256: 'a'.repeat(64), definition: { poses: [] } }))
    .toMatchObject({ evaluated_command_kind: 'placement-poses' })
  await f.controller.resetDraft()
  expect(f.controller.getState().draft).toEqual({})
  expect(f.api.evaluate.mock.lastCall[0].params).toEqual({})
  await f.controller.apply()
  expect(f.api.apply.mock.lastCall[0].params).toEqual({})
})

it('rejects an unsolicited evaluated placement upgrade without granting it draft authority', async () => {
  const f = await transformFixture('cluster_op', { evaluate: vi.fn(async body =>
    transformPacket(body, 'cluster_op', { evaluated_command_kind: 'placement-poses' })) })
  await f.controller.open('feature'); const original = f.controller.getState().projection
  await f.controller.update({ translation: [1, 0, 0] })
  expect(f.controller.getState().projection).toBe(original)
  expect(f.controller.getState().error).toBeInstanceOf(Error)
  await f.controller.apply(); expect(f.api.apply).not.toHaveBeenCalled()
})
