import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPartRepairController } from './part_repair_controller.js'
import { RepairRequestError } from '../api/part_repair_endpoints.js'

// The real commit endpoint publishes first and returns metadata, never Design.
// This regression intentionally does not use the older design-bearing mock.
const receipt = { job_id: 'job', status: 'committed', revision: 5, design_id: 'part' }
const controllers = []
function setup() {
  let context = { docId: 'origin', designId: 'part', loadoutId: 'main', revision: 4,
    editable: true, cursor: -1, subCursor: null }
  const draft = { draft_id: 'draft', generation: 0, actions: [] }
  const api = {
    inspect: vi.fn(async () => ({ design_id: 'part', revision: 4, draft, repair_draft: { draft_id: 'draft', generation: 0 } })),
    acknowledge: vi.fn(() => true),
    evaluate: vi.fn(async () => ({ job_id: 'job', repair_draft: { draft_id: 'draft', generation: 0 } })),
    poll: vi.fn(async () => ({ status: 'complete', result: { status: 'ready', issues: [] } })),
    commit: vi.fn(async () => receipt),
    refreshCommitted: vi.fn(async () => ({ revision: 5, design: { id: 'part' }, nucleotides: [], helix_axes: [] })),
    apply: vi.fn(value => {
      if (!value.design) throw new Error('Commit receipt is not a displayed design')
      context = { ...context, revision: value.revision }
      return Promise.resolve(value)
    }),
    cancel: vi.fn(async () => ({})),
  }
  const controller = createPartRepairController({ api, getContext: () => context, events: new EventTarget() })
  controllers.push(controller)
  return { api, controller, navigate: () => { context = { ...context, docId: 'different' }; controller.refreshContext() } }
}
async function ready(h) { await h.controller.inspect(); await h.controller.evaluate(); await h.controller.poll() }
beforeEach(() => vi.useFakeTimers())
afterEach(() => { for (const controller of controllers.splice(0)) controller.dispose(); vi.useRealTimers() })

it('refreshes the exact published revision after a metadata-only commit before normal scene synchronization', async () => {
  const h = setup(); await ready(h); await h.controller.apply()
  expect(h.api.commit).toHaveBeenCalledTimes(1)
  expect(h.api.refreshCommitted).toHaveBeenCalledWith(receipt, { context: expect.objectContaining({ docId: 'origin', revision: 4 }), signal: expect.anything() })
  expect(h.api.apply).toHaveBeenCalledWith(expect.objectContaining({ revision: 5, design: { id: 'part' }, nucleotides: [] }), expect.objectContaining({ revision: 4 }))
  expect(h.controller.getState()).toMatchObject({ committed: receipt, refreshNeeded: false, ready: false, job: null })
  expect(h.api.cancel).not.toHaveBeenCalled()
})

it('retains successful publication when refresh fails and retries only the read', async () => {
  const h = setup(); await ready(h)
  h.api.refreshCommitted.mockRejectedValueOnce(new Error('Display request failed'))
  await h.controller.apply()
  expect(h.controller.getState()).toMatchObject({ committed: receipt, refreshNeeded: true, ready: false, job: null })
  expect(h.api.apply).not.toHaveBeenCalled()
  await h.controller.apply(); h.controller.cancel()
  expect(h.api.commit).toHaveBeenCalledTimes(1)
  expect(h.api.cancel).not.toHaveBeenCalled()
  await h.controller.refreshCommitted()
  expect(h.api.refreshCommitted).toHaveBeenCalledTimes(2)
  expect(h.controller.getState()).toMatchObject({ committed: receipt, refreshNeeded: false })
  expect(h.api.apply).toHaveBeenCalledTimes(1)
})

it('never applies a late committed refresh to a different document or cancels a published job', async () => {
  const h = setup(); await ready(h)
  let resolve
  h.api.refreshCommitted.mockReturnValueOnce(new Promise(yes => { resolve = yes }))
  const applying = h.controller.apply()
  for (let index = 0; index < 8; index++) await Promise.resolve()
  expect(h.controller.getState().committed).toEqual(receipt)
  h.navigate()
  resolve({ revision: 5, design: { id: 'part' }, nucleotides: [], helix_axes: [] })
  await applying
  expect(h.api.apply).not.toHaveBeenCalled()
  expect(h.api.cancel).not.toHaveBeenCalled()
  expect(h.controller.getState().committed).toBeNull()
})

it('retains and explicitly resolves a publication whose response was lost, without recommitting', async () => {
  const h = setup(); await ready(h)
  h.api.commit.mockRejectedValueOnce(new RepairRequestError(0, 'Connection lost after publication'))
  await h.controller.apply()
  expect(h.controller.getState()).toMatchObject({ ready: false, job: null,
    publication: { jobId: 'job', outcome: 'unknown' } })
  h.controller.cancel()
  expect(h.api.cancel).not.toHaveBeenCalled()
  h.api.poll.mockResolvedValue({ job_id: 'job', status: 'committed', revision: 5, stale: false, source_busy: false })
  await h.controller.resolvePublication()
  expect(h.api.commit).toHaveBeenCalledTimes(1)
  expect(h.api.refreshCommitted).toHaveBeenCalledTimes(1)
  expect(h.api.apply).toHaveBeenCalledTimes(1)
  expect(h.controller.getState()).toMatchObject({ publication: null, committed: receipt, refreshNeeded: false })
})

it('keeps a documented prepublication rejection distinct from an unknown network outcome', async () => {
  const h = setup(); await ready(h)
  h.api.commit.mockRejectedValueOnce(new RepairRequestError(429, 'A part history operation is already running'))
  await h.controller.apply()
  expect(h.controller.getState()).toMatchObject({ publication: null, committed: null, ready: false,
    job: { id: 'job', response: null } })
  h.controller.cancel()
  expect(h.api.cancel).toHaveBeenCalledTimes(1)
  expect(h.api.refreshCommitted).not.toHaveBeenCalled()
})
