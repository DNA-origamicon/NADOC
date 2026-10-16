import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPartRepairController } from './part_repair_controller.js'
import { RepairRequestError } from '../api/part_repair_endpoints.js'

const action = { action: 'set_input', feature_id: 'feature', child_id: null,
  parameter_path: ['name'], expected_old: 'Old', value: 'New' }
const savedDraft = () => ({ version: 1, draft_id: 'draft', generation: 0, actions: [action], base: { commands_sha256: 'base' } })
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const controllers = []

function setup({ draft = savedDraft(), editable = true } = {}) {
  let context = { docId: 'original-doc', designId: 'part', loadoutId: 'main', revision: 4,
    editable, cursor: -1, subCursor: null, summary: null }, nextJob = 0
  const watchers = new Set(), events = new EventTarget()
  const metadata = () => ({ design_id: context.designId, revision: context.revision,
    draft, repair_draft: draft ? { draft_id: draft.draft_id, generation: draft.generation, status: 'pending' } : null })
  const changeContext = patch => { context = { ...context, ...patch }; for (const fn of watchers) fn() }
  const api = {
    inspect: vi.fn(async () => metadata()),
    inspectInputs: vi.fn(async target => ({ version: 1, assessment: 'inputs_only', design_id: target.expected_design_id,
      revision: target.expected_revision, feature_id: target.feature_id, child_id: target.child_id,
      definition_supported: true, fields: [] })),
    mutate: vi.fn(async body => {
      draft = body.operation === 'discard' ? null : { ...(draft ?? savedDraft()),
        generation: body.operation === 'create' ? 0 : draft.generation + 1,
        actions: body.actions ?? draft.actions }
      return { ...metadata(), revision: context.revision + 1 }
    }),
    acknowledge: vi.fn(json => { changeContext({ revision: json.revision, summary: json.repair_draft }); return true }),
    evaluate: vi.fn(async body => ({ job_id: `job-${++nextJob}`, status: 'running', source_revision: body.expected_revision,
      repair_draft: { draft_id: body.expected_draft_id, generation: body.expected_generation } })),
    start: vi.fn(async () => ({ job_id: `job-${++nextJob}`, status: 'running' })),
    poll: vi.fn(async () => ({ status: 'running', result: null })),
    cancel: vi.fn(async () => ({})),
    commit: vi.fn(async id => ({ job_id: id, status: 'committed', design_id: 'part', revision: context.revision + 1 })),
    refreshCommitted: vi.fn(async receipt => ({ design: { id: 'part' }, revision: receipt.revision, nucleotides: [], helix_axes: [] })),
    apply: vi.fn(json => { changeContext({ revision: json.revision }); return Promise.resolve(json) }),
    inspectSource: vi.fn(async value => ({ ...value, expected_blob: { state: 'missing' } })),
    uploadSource: vi.fn(async () => ({ ...metadata(), revision: context.revision + 1,
      repair_draft: { ...metadata().repair_draft, base_status: 'rebase_required' }, published_source_changed: true })),
  }
  const controller = createPartRepairController({ api, getContext: () => context, events,
    subscribeContext: fn => { watchers.add(fn); return () => watchers.delete(fn) } })
  controllers.push(controller)
  return { api, controller, events, changeContext, context: () => context, watchers }
}
async function ready(h) {
  await h.controller.inspect(); await h.controller.evaluate()
  h.api.poll.mockResolvedValue({ status: 'complete', stale: false, source_busy: false,
    result: { status: 'ready', issues: [], repair: { authoring_changes: { changed_fields: ['protein_assets'] } } } })
  await h.controller.poll()
  expect(h.controller.getState().ready).toBe(true)
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => { for (const controller of controllers.splice(0)) controller.dispose(); vi.useRealTimers() })

describe('part repair lifecycle', () => {
  it('does no background proof or metadata request on construction and never trusts saved readiness', async () => {
    const h = setup({ draft: { ...savedDraft(), status: 'ready' } })
    expect(h.api.inspect).not.toHaveBeenCalled(); expect(h.api.start).not.toHaveBeenCalled()
    expect(h.controller.getState().publishedStatus).toBe('unchecked')
    await h.controller.inspect()
    expect(h.controller.getState()).toMatchObject({ loaded: true, ready: false, job: null })
    expect(h.api.apply).not.toHaveBeenCalled()
  })

  it('creates, updates and discards using exact current guards and one metadata acknowledgement', async () => {
    const h = setup({ draft: null })
    await h.controller.inspect()
    await h.controller.save([action])
    expect(h.api.mutate.mock.calls[0][0]).toEqual({ draft_version: 1, operation: 'create', expected_design_id: 'part',
      expected_revision: 4, expected_draft_id: null, expected_generation: null, actions: [action] })
    expect(h.controller.getState().context.revision).toBe(5)
    await h.controller.save([{ ...action, value: 'Newer' }])
    expect(h.api.mutate.mock.calls[1][0]).toMatchObject({ operation: 'update', expected_revision: 5, expected_draft_id: 'draft', expected_generation: 0 })
    await h.controller.discard()
    expect(h.controller.getState()).toMatchObject({ draft: null, loaded: true, ready: false, busy: null })
    expect(h.api.apply).not.toHaveBeenCalled()
  })

  it('requires explicit rebase and preserves exact expectations when no revised actions were supplied', async () => {
    const h = setup(); await h.controller.inspect()
    h.api.evaluate.mockRejectedValueOnce(new RepairRequestError(409, { code: 'draft_rebase_required', detail: 'Published source changed' }))
    await h.controller.evaluate()
    expect(h.controller.getState().issues[0].code).toBe('draft_rebase_required')
    expect(h.api.mutate).not.toHaveBeenCalled()
    await h.controller.rebase()
    expect(h.api.mutate.mock.calls[0][0]).not.toHaveProperty('actions')
    expect(h.controller.getState().draft.actions[0].expected_old).toBe('Old')
  })

  it('keeps a candidate private until Apply, and retains the proposal after commit', async () => {
    const h = setup(); await ready(h)
    expect(h.api.apply).not.toHaveBeenCalled()
    await h.controller.apply()
    expect(h.api.commit).toHaveBeenCalledTimes(1)
    expect(h.api.apply).toHaveBeenCalledTimes(1)
    expect(h.controller.getState()).toMatchObject({ ready: false, job: null, busy: null,
      draft: { draft_id: 'draft', generation: 0 }, summary: { base_status: 'rebase_required' } })
    await h.controller.apply()
    expect(h.api.commit).toHaveBeenCalledTimes(1)
  })

  it.each([{ revision: 5 }, { loadoutId: 'other' }, { designId: 'other' }, { docId: 'new-doc' }])('invalidates ready results when context changes %s', async change => {
    const h = setup(); await ready(h)
    h.changeContext(change)
    expect(h.controller.getState()).toMatchObject({ ready: false, job: null, loaded: false })
    expect(h.api.cancel).toHaveBeenCalledWith('job-1', { context: expect.objectContaining({ docId: 'original-doc', revision: 4 }) })
    await h.controller.apply()
    expect(h.api.commit).not.toHaveBeenCalled()
  })

  it('cancels late start replies in their original document and ignores same-ID reset ABA', async () => {
    const h = setup(), pending = deferred()
    await h.controller.inspect()
    h.api.evaluate.mockReturnValueOnce(pending.promise)
    const start = h.controller.evaluate()
    h.events.dispatchEvent(new Event('nadoc:document-reset'))
    pending.resolve({ job_id: 'late-job', repair_draft: { draft_id: 'draft', generation: 0 } })
    await start
    expect(h.controller.getState().job).toBeNull()
    expect(h.api.cancel).toHaveBeenCalledWith('late-job', { context: expect.objectContaining({ docId: 'original-doc' }) })
  })

  it('ignores late metadata acknowledgements after navigation', async () => {
    const h = setup(), pending = deferred()
    h.api.inspect.mockReturnValueOnce(pending.promise)
    const inspecting = h.controller.inspect()
    h.changeContext({ designId: 'different' })
    pending.resolve({ design_id: 'part', revision: 50, draft: savedDraft() })
    await inspecting
    expect(h.api.acknowledge).not.toHaveBeenCalled()
    expect(h.controller.getState().draft).toBeNull()
  })

  it('does not adopt a newer metadata GET revision while published geometry remains stale', async () => {
    const h = setup()
    h.api.inspect.mockResolvedValueOnce({ design_id: 'part', revision: 5, draft: savedDraft() })
    await h.controller.inspect()
    expect(h.api.acknowledge).not.toHaveBeenCalled()
    expect(h.context().revision).toBe(4)
    expect(h.controller.getState()).toMatchObject({ loaded: false, draft: null, busy: null })
    expect(h.controller.getState().error.message).toMatch(/Refresh the design/)
  })

  it('reports a display refresh failure after commit without restoring apply readiness', async () => {
    const h = setup(); await ready(h)
    h.api.apply.mockImplementationOnce(json => {
      h.changeContext({ revision: json.revision })
      return Promise.reject(new Error('Geometry display refresh failed'))
    })
    await h.controller.apply()
    expect(h.controller.getState()).toMatchObject({ ready: false, job: null, busy: null })
    expect(h.controller.getState().error.message).toBe('Geometry display refresh failed')
    await h.controller.apply()
    expect(h.api.commit).toHaveBeenCalledTimes(1)
  })

  it('keeps a single poll per job, clears readiness on expiry and never retains candidate bytes', async () => {
    const h = setup(), pending = deferred()
    await h.controller.inspect(); await h.controller.evaluate()
    h.api.poll.mockReturnValueOnce(pending.promise)
    const first = h.controller.poll(); await h.controller.poll()
    expect(h.api.poll).toHaveBeenCalledTimes(1)
    pending.resolve({ status: 'complete', result: { status: 'ready', candidate: { geometry: 'forbidden' } } })
    await first
    expect(h.controller.getState().result).not.toHaveProperty('candidate')
    expect(h.controller.getState().ready).toBe(true)
    h.api.poll.mockRejectedValueOnce(new RepairRequestError(410, 'Result expired'))
    await vi.advanceTimersByTimeAsync(5000)
    expect(h.controller.getState().ready).toBe(false)
    expect(h.controller.getState().error.status).toBe(410)
  })

  it('selection is never publishable, preserves typed target paths and hides stale choices', async () => {
    const h = setup()
    const target = { feature_id: 'copy', parameter_path: ['protein_ids', 0], expected_old: 'missing', limit: 100 }
    await h.controller.selectReferences(target)
    expect(h.api.start.mock.calls[0][0].selection).toMatchObject({ ...target, expected_design_id: 'part', expected_revision: 4 })
    h.api.poll.mockResolvedValue({ status: 'complete', result: { status: 'preview', selection: { candidates: [{ identity: 'chosen' }] } } })
    await h.controller.poll()
    expect(h.controller.getState().selection.candidates).toHaveLength(1)
    expect(h.controller.getState().ready).toBe(false)
    h.changeContext({ revision: 5 })
    expect(h.controller.getState().selection).toBeNull()
  })

  it('restores source metadata without applying geometry or silently rebasing the saved proposal', async () => {
    const h = setup(); await h.controller.inspect()
    const draft = h.controller.getState().draft
    const receipt = await h.controller.inspectSource({ operation: 'restore_published', feature_id: 'feature', parameter: 'source', source: { size_bytes: 3 } })
    expect(receipt).not.toHaveProperty('draft_version')
    expect(receipt).toMatchObject({ expected_revision: 4, expected_draft_id: 'draft', expected_generation: 0 })
    await h.controller.uploadSource(receipt, new Blob(['PDB']))
    expect(h.controller.getState().draft).toBe(draft)
    expect(h.controller.getState()).toMatchObject({ ready: false, context: { revision: 5 }, summary: { base_status: 'rebase_required' } })
    expect(h.api.mutate).not.toHaveBeenCalled(); expect(h.api.apply).not.toHaveBeenCalled()
  })

  it('allows protected-loadout inspection but rejects mutation without changing targets', async () => {
    const h = setup({ editable: false }); await h.controller.inspect()
    await h.controller.save([action]); await h.controller.evaluate()
    expect(h.api.inspect).toHaveBeenCalledTimes(1)
    expect(h.api.mutate).not.toHaveBeenCalled(); expect(h.api.evaluate).not.toHaveBeenCalled()
    expect(h.context().loadoutId).toBe('main')
  })

  it('requests input descriptors only on demand and rejects a catalog from another revision', async () => {
    const h = setup()
    expect(h.api.inspectInputs).not.toHaveBeenCalled()
    await h.controller.inspectInputs({ feature_id: 'group', child_id: 'child' })
    expect(h.api.inspectInputs.mock.calls[0][0]).toEqual({ expected_design_id: 'part', expected_revision: 4,
      feature_id: 'group', child_id: 'child' })
    expect(h.controller.getState().inputs.feature_id).toBe('group')
    h.api.inspectInputs.mockResolvedValueOnce({ version: 1, assessment: 'inputs_only', design_id: 'part', revision: 3, feature_id: 'group', child_id: 'child' })
    await h.controller.inspectInputs({ feature_id: 'group', child_id: 'child' })
    expect(h.controller.getState().error.message).toMatch(/another feature or revision/)
  })

  it('does not execute numerical upgrades before the separate molecular comparison review exists', async () => {
    const h = setup({ draft: { ...savedDraft(), actions: [{ action: 'upgrade_numerical_contract', feature_id: 'relax', expected_engine: {} }] } })
    await h.controller.inspect(); await h.controller.evaluate()
    expect(h.controller.getState().requiresReview).toBe(true)
    expect(h.api.evaluate).not.toHaveBeenCalled()
    expect(h.controller.getState().error.message).toMatch(/atom and junction comparison/)
  })

  it('disposes subscriptions, requests, polls and private candidates', async () => {
    const h = setup(); await ready(h)
    h.controller.dispose()
    expect(h.watchers.size).toBe(0)
    expect(vi.getTimerCount()).toBe(0)
    expect(h.api.cancel).toHaveBeenCalledTimes(1)
  })
})
