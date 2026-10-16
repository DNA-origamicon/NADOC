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
async function fixture(overrides = {}) {
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
    validateDisplay, applyPublished, events, uuid: () => PREVIEW, now: () => Date.now() })
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
