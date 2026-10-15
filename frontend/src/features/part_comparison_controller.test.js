import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPartComparisonController } from './part_comparison_controller.js'
import { RepairRequestError } from '../api/part_repair_endpoints.js'
import { comparisonEnvelope, deferredComparison, readyRepairState } from '../test-helpers/part_comparison.js'

const controllers = []
function setup() {
  let current = readyRepairState(), elapsed = 0
  const listeners = new Set(), events = new EventTarget()
  const repair = { getState: () => current,
    subscribe: fn => { listeners.add(fn); fn(current); return () => listeners.delete(fn) },
    cancel: vi.fn(), apply: vi.fn(), evaluate: vi.fn(), poll: vi.fn() }
  const api = { compare: vi.fn(async () => comparisonEnvelope()), acknowledge: vi.fn(), apply: vi.fn(), cancel: vi.fn() }
  const controller = createPartComparisonController({ api, repair, events, now: () => elapsed })
  controllers.push(controller)
  const change = mutate => { current = mutate(current); for (const fn of listeners) fn(current) }
  return { api, repair, controller, events, listeners, change, advanceClock: ms => { elapsed += ms } }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => { for (const controller of controllers.splice(0)) controller.dispose(); vi.useRealTimers() })

describe('private comparison lifetime', () => {
  it('does no background request, then binds one explicit read to the saved evaluated job', async () => {
    const h = setup(), before = JSON.stringify(h.repair.getState())
    expect(h.api.compare).not.toHaveBeenCalled()
    await h.controller.open()
    expect(h.api.compare).toHaveBeenCalledExactlyOnceWith('job', {
      projection_version: 1, expected_design_id: 'part', expected_revision: 4,
      expected_draft_id: 'draft', expected_generation: 3,
    }, { context: h.repair.getState().context, signal: expect.any(AbortSignal) })
    expect(h.controller.getState()).toMatchObject({ open: true, busy: false, error: null,
      projection: { job_id: 'job', source_revision: 4 } })
    expect(JSON.stringify(h.repair.getState())).toBe(before)
    for (const name of ['cancel', 'apply', 'evaluate', 'poll']) expect(h.repair[name]).not.toHaveBeenCalled()
    expect(h.api.acknowledge).not.toHaveBeenCalled(); expect(h.api.apply).not.toHaveBeenCalled()
  })

  it('refuses saved readiness without a live current repair job', async () => {
    const h = setup(); h.change(state => ({ ...state, job: null, ready: true }))
    await h.controller.open()
    expect(h.api.compare).not.toHaveBeenCalled()
    expect(h.controller.getState().projection).toBeNull()
    expect(h.controller.getState().error).toBeTruthy()
  })

  it('never queues duplicate reads and does not repeat a complete current projection', async () => {
    const h = setup(), pending = deferredComparison()
    h.api.compare.mockReturnValueOnce(pending.promise)
    const first = h.controller.open(); await h.controller.open()
    expect(h.api.compare).toHaveBeenCalledOnce()
    pending.resolve(comparisonEnvelope()); await first; await h.controller.open()
    expect(h.api.compare).toHaveBeenCalledOnce()
  })

  it.each([
    ['document', state => ({ ...state, context: { ...state.context, docId: 'other' } })],
    ['part', state => ({ ...state, context: { ...state.context, designId: 'other' } })],
    ['loadout', state => ({ ...state, context: { ...state.context, loadoutId: 'other' } })],
    ['revision', state => ({ ...state, context: { ...state.context, revision: 5 } })],
    ['cursor', state => ({ ...state, context: { ...state.context, cursor: 0 } })],
    ['draft', state => ({ ...state, draft: { ...state.draft, draft_id: 'other' } })],
    ['generation', state => ({ ...state, draft: { ...state.draft, generation: 4 } })],
    ['job', state => ({ ...state, job: { ...state.job, id: 'new-job' } })],
    ['cancellation', state => ({ ...state, ready: false, job: null })],
    ['busy source', state => ({ ...state, job: { ...state.job, response: { ...state.job.response, source_busy: true } } })],
    ['stale source', state => ({ ...state, job: { ...state.job, response: { ...state.job.response, stale: true } } })],
    ['publication', state => ({ ...state, publication: { outcome: 'pending' } })],
  ])('discards a late projection after %s changes even when transport ignores abort', async (_label, mutate) => {
    const h = setup(), pending = deferredComparison(), painted = []
    h.controller.subscribe(value => { if (value.projection) painted.push(value.projection) })
    h.api.compare.mockReturnValueOnce(pending.promise)
    const reading = h.controller.open()
    const signal = h.api.compare.mock.calls[0][2].signal
    h.change(mutate)
    expect(signal.aborted).toBe(true)
    pending.resolve(comparisonEnvelope()); await reading
    expect(painted).toHaveLength(0)
    expect(h.controller.getState()).toMatchObject({ projection: null, busy: false })
    expect(vi.getTimerCount()).toBe(0)
    expect(h.api.cancel).not.toHaveBeenCalled()
  })

  it('clears a displayed projection on same-ID document-session reset', async () => {
    const h = setup(); await h.controller.open()
    h.events.dispatchEvent(new Event('nadoc:document-reset'))
    expect(h.controller.getState()).toMatchObject({ open: false, projection: null })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not invalidate an unchanged job merely because its status poll creates a new object', async () => {
    const h = setup(); await h.controller.open()
    const displayed = h.controller.getState().projection
    h.change(state => ({ ...state, job: { ...state.job, response: { ...state.job.response } } }))
    expect(h.controller.getState().projection).toBe(displayed)
    expect(h.api.compare).toHaveBeenCalledOnce()
  })

  it('keeps the original evaluated repair available when comparison is unsupported', async () => {
    const h = setup(), job = h.repair.getState().job
    const detail = { code: 'unsupported_comparison_scope', detail: 'Comparison does not yet cover helices' }
    h.api.compare.mockRejectedValueOnce(new RepairRequestError(422, detail))
    await h.controller.open()
    expect(h.controller.getState()).toMatchObject({ projection: null, busy: false,
      error: { status: 422, detail }, issues: [detail] })
    expect(h.repair.getState().job).toBe(job)
    expect(h.repair.getState().ready).toBe(true)
    expect(h.repair.cancel).not.toHaveBeenCalled(); expect(h.api.cancel).not.toHaveBeenCalled()
  })

  it('rejects a mismatched or partial response without displaying either pane', async () => {
    const h = setup(), packet = comparisonEnvelope()
    packet.repair_draft.generation++
    h.api.compare.mockResolvedValueOnce(packet)
    await h.controller.open()
    expect(h.controller.getState().projection).toBeNull()
    expect(h.controller.getState().error).toBeTruthy()
    expect(h.repair.getState().ready).toBe(true)
  })

  it('charges transport time against the remaining lease and clears both panes at expiry', async () => {
    const h = setup(), pending = deferredComparison()
    h.api.compare.mockReturnValueOnce(pending.promise)
    const reading = h.controller.open()
    h.advanceClock(10000)
    pending.resolve(comparisonEnvelope()); await reading
    await vi.advanceTimersByTimeAsync(49999)
    expect(h.controller.getState().projection).not.toBeNull()
    await vi.advanceTimersByTimeAsync(1)
    expect(h.controller.getState().projection).toBeNull()
    expect(h.controller.getState().error.message).toMatch(/expired/i)
    expect(vi.getTimerCount()).toBe(0)
    expect(h.api.compare).toHaveBeenCalledOnce()
    expect(h.repair.poll).not.toHaveBeenCalled()
  })

  it('never paints a response whose conservative lease already expired in transit', async () => {
    const h = setup(), pending = deferredComparison(), painted = []
    h.controller.subscribe(value => { if (value.projection) painted.push(value.projection) })
    h.api.compare.mockReturnValueOnce(pending.promise)
    const reading = h.controller.open(); h.advanceClock(61000)
    pending.resolve(comparisonEnvelope()); await reading
    expect(painted).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('closing aborts only this read, and reopening is protected from the old response', async () => {
    const h = setup(), first = deferredComparison(), second = deferredComparison()
    h.api.compare.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const old = h.controller.open(), signal = h.api.compare.mock.calls[0][2].signal
    h.controller.close(); expect(signal.aborted).toBe(true)
    const fresh = h.controller.open(), packet = comparisonEnvelope()
    packet.proposed.particles[0].diameter_nm = 14
    second.resolve(packet); await fresh
    first.resolve(comparisonEnvelope()); await old
    expect(h.controller.getState().projection.proposed.particles[0].diameter_nm).toBe(14)
    expect(h.api.cancel).not.toHaveBeenCalled(); expect(h.repair.cancel).not.toHaveBeenCalled()
  })

  it('dispose releases subscriptions, requests and expiry timers without touching repair publication', async () => {
    const h = setup(); await h.controller.open()
    const changed = vi.fn(); h.controller.subscribe(changed); changed.mockClear()
    h.controller.dispose(); h.controller.dispose()
    expect(h.listeners.size).toBe(0); expect(vi.getTimerCount()).toBe(0)
    h.events.dispatchEvent(new Event('nadoc:document-reset'))
    expect(changed).not.toHaveBeenCalled()
    expect(h.repair.cancel).not.toHaveBeenCalled(); expect(h.repair.apply).not.toHaveBeenCalled()
  })

  it('leaves no expiry timer or returned display when a subscriber closes during publication', async () => {
    const h = setup()
    h.controller.subscribe(value => { if (value.projection) h.controller.close() })
    expect(await h.controller.open()).toBeNull()
    expect(h.controller.getState()).toMatchObject({ open: false, projection: null })
    expect(vi.getTimerCount()).toBe(0)
  })
})
