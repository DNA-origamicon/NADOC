import { describe, expect, it, vi } from 'vitest'
import { normalizeVRToolConfig, vrToolConfigMissing } from './vr_tool_config.js'
import { buildVRParameterizedToolPlan, evaluateVRToolPreflight } from './vr_tool_execution_plan.js'
import { createVRToolPreflightCoordinator } from './vr_tool_preflight_coordinator.js'
import { createVRToolTransactionCoordinator, vrToolExecutionFeedback } from './vr_tool_transaction.js'
import { createVRSweepCommit } from './vr_sweep_commit.js'

const draft = () => ({ mode: 'sweep', target_kind: 'none', target_identity: null, target_owner_tokens: [],
  painted_footprint: { lattice_type: 'HONEYCOMB', cells: [[0, 0], [0, 1]] }, extrude_from: 'XY',
  points_nm: [[0, 0, 0], [0, 0, 10], [5, 3, 18]], strand_filter: 'both', ligate_adjacent: true })
const design = () => ({ id: 'doc', lattice_type: 'HONEYCOMB', feature_log: [] })

describe('native Sweep transport and canonical desktop plan', () => {
  it('rejects occupied source cells across frames while distinguishing planes', () => {
    const doc = { ...design(), lattice_frames: [{id:'a',plane:'XY'},{id:'b',plane:'YZ'}],
      helices: [{id:'h1',lattice_frame_id:'a',grid_pos:[0,0]}, {id:'h2',lattice_frame_id:'b',grid_pos:[2,3]}] }
    expect(buildVRParameterizedToolPlan(draft(), {design:doc,revision:1}).reason).toBe('painted_cell_occupied')
    expect(buildVRParameterizedToolPlan({...draft(),extrude_from:'YZ'}, {design:doc,revision:1}).accepted).toBe(true)
  })
  it('copies model-space deltas and does not require an existing selection', () => {
    const raw = draft(), normalized = normalizeVRToolConfig(raw)
    expect(normalized).toEqual(raw)
    raw.points_nm[1][2] = 123
    expect(normalized.points_nm[1]).toEqual([0, 0, 10])
    expect(vrToolConfigMissing(normalized)).toEqual([])
    const result = buildVRParameterizedToolPlan(normalized, { design: design(), revision: 4 })
    expect(result.accepted).toBe(true)
    expect(result.plan.commit).toEqual({ apiMethod: 'createSweep', arguments: {
      expected_design_id: 'doc', expected_revision: 4, cells: [[0, 0], [0, 1]],
      points_nm: normalized.points_nm, plane: 'XY', strand_filter: 'both', ligate_adjacent: true,
    } })
  })
  it('keeps incomplete paint/free-draw drafts valid while blocking confirmation', () => {
    const raw = draft(); raw.points_nm = []; raw.painted_footprint.cells = []
    expect(vrToolConfigMissing(raw)).toEqual(['footprint', 'points'])
    expect(buildVRParameterizedToolPlan(raw, { design: design(), revision: 1 }).reason).toBe('paint_cells_required')
    raw.painted_footprint.cells.push([0, 0])
    expect(buildVRParameterizedToolPlan(raw, { design: design(), revision: 1 }).reason).toBe('path_points_required')
  })
  it('builds a new bundle even if desktop has an unrelated selected target', () => {
    const result = buildVRParameterizedToolPlan(draft(), { design: design(), revision: 4,
      toolTarget: { identity: 'nuc:unrelated', selectionKind: 'end', ownerTokens: ['owner:1'],
        selectedRef: { kind: 'end' } } })
    expect(result.accepted).toBe(true)
    expect(result.plan.commit.arguments.source_helix_id).toBeUndefined()
  })
  it.each([
    { points_nm: [[1, 0, 0], [0, 0, 1]] }, { points_nm: [[0, 0, 0], [NaN, 0, 1]] },
    { points_nm: [[0, 0, 0], [0, 10001, 0]] }, { points_nm: Array.from({ length: 257 }, () => [0, 0, 0]) },
    { freeform_placement: {} }, { source_helix_id: 'h1' }, { target_kind: 'end' },
    { painted_footprint: { lattice_type: 'HONEYCOMB', cells: [[10001, 0]] } },
  ])('rejects unsupported placement or unbounded points: %j', changes => {
    expect(normalizeVRToolConfig({ ...draft(), ...changes })).toBeNull()
  })
  it('uses read-only Sweep preview, checks its revision, and reports errors', async () => {
    const api = { previewSweep: vi.fn(async () => ({ length_nm: 21, revision: 4 })),
      currentRevisionWatermark: () => 4, createSweep: vi.fn() }
    const environment = { design: design(), api }
    expect((await evaluateVRToolPreflight(9, draft(), environment)).feedback).toMatchObject({
      tool_mode: 'sweep', tool_config_sequence: 9, target_kind: 'none', status: 'ok',
    })
    expect(api.createSweep).not.toHaveBeenCalled()
    expect(api.previewSweep).toHaveBeenCalledWith(expect.objectContaining({ expected_revision: 4 }), null, { includeGeometry: true })
    api.previewSweep.mockResolvedValue({ length_nm: 21, revision: 5 })
    expect((await evaluateVRToolPreflight(10, draft(), environment)).feedback.status).toBe('error')
    api.previewSweep.mockRejectedValue(new Error('Invalid path'))
    expect((await evaluateVRToolPreflight(11, draft(), environment)).feedback.reason).toBe('request_failed')
  })
})

async function harness() {
  const state = { currentDesign: design() }
  let revision = 4
  const api = { currentRevisionWatermark: () => revision,
    previewSweep: vi.fn(async () => ({ length_nm: 21, revision })),
    createSweep: vi.fn(async () => {
      state.currentDesign.feature_log.push({ id: 'sweep-entry' }); revision++
      return { vr_transaction: { feature_log_entry_id: 'sweep-entry', target_count: 2 } }
    }), refreshNativeVRScene: vi.fn(async () => ({ published: true })) }
  const undoDesign = vi.fn(async () => { state.currentDesign.feature_log.pop(); revision++; return {} })
  const transaction = createVRToolTransactionCoordinator({ getState: () => state, undoDesign })
  const preflight = createVRToolPreflightCoordinator({ sendFeedback: async () => ({ published: true }) })
  await preflight.request(7, draft(), { design: state.currentDesign, api })
  const sendFeedback = vi.fn(async (event, status, reason, transaction) => {
    const payload = vrToolExecutionFeedback({ event, status, reason, transaction, executionSequence: 1 })
    return payload ? { published: true } : null
  }), onOutcome = vi.fn()
  const controller = createVRSweepCommit({ preflight, transaction, api, getState: () => state, sendFeedback, onOutcome })
  const event = { mode: 'sweep', action: 'confirm', targetKind: 'none', targetIdentity: null,
    targetOwnerTokens: [], sequence: 1, configSequence: 7 }
  return { state, api, preflight, sendFeedback, onOutcome, controller, event, undoDesign }
}

describe('Sweep confirm, cancellation and exact-tail undo', () => {
  it('builds the real browser feedback for independent Sweep and refuses missing Move targets', () => {
    const event = { mode: 'sweep', action: 'confirm', sequence: 1, targetKind: 'none', targetIdentity: null }
    const pending = { event, status: 'pending', reason: 'committing', executionSequence: 2 }
    expect(vrToolExecutionFeedback(pending)).toMatchObject({ tool_mode: 'sweep', target_kind: 'none', target_identity: null })
    expect(vrToolExecutionFeedback({ ...pending, event: { ...event, mode: 'move_rotate' } })).toBeNull()
    expect(vrToolExecutionFeedback({ ...pending, status: 'succeeded',
      event: { ...event, action: 'undo', targetIdentity: 'later-selection', targetKind: 'end' },
      transaction: { targetIdentity: null, targetKind: 'none', featureLogEntryId: 'sweep-entry' } }))
      .toMatchObject({ target_identity: null, target_kind: 'none', feature_log_entry_id: 'sweep-entry' })
  })
  it('commits the acknowledged draft once and refreshes native geometry after commit/undo', async () => {
    const h = await harness()
    expect((await h.controller.handle(h.event)).accepted).toBe(true)
    expect(h.sendFeedback.mock.calls.map(call => call[1])).toEqual(['pending', 'succeeded'])
    expect((await h.controller.handle(h.event)).reason).toBe('invalid_or_stale')
    expect(h.api.createSweep).toHaveBeenCalledTimes(1)
    expect((await h.controller.handle({ ...h.event, sequence: 2, action: 'undo' })).reason).toBe('undone')
    expect(h.api.refreshNativeVRScene).toHaveBeenCalledTimes(2)
  })
  it('requires the exact preview revision and action-time configuration', async () => {
    const h = await harness()
    expect((await h.controller.handle({ ...h.event, configSequence: 6 })).reason).toBe('validated_draft_required')
    h.state.currentDesign.id = 'another-document'
    expect((await h.controller.handle({ ...h.event, sequence: 2 })).reason).toBe('document_changed')
    expect(h.api.createSweep).not.toHaveBeenCalled()
  })
  it('cancels without mutating and invalidates the formerly validated plan', async () => {
    const h = await harness()
    expect((await h.controller.handle({ ...h.event, action: 'cancel' })).reason).toBe('cancelled')
    expect((await h.controller.handle({ ...h.event, sequence: 2 })).reason).toBe('validated_draft_required')
    expect(h.api.createSweep).not.toHaveBeenCalled()
  })
  it('refuses undo after an unrelated desktop edit', async () => {
    const h = await harness(); await h.controller.handle(h.event)
    h.state.currentDesign.feature_log.push({ id: 'desktop-edit' })
    expect((await h.controller.handle({ ...h.event, sequence: 2, action: 'undo' })).reason).toBe('undo_stale_desktop_changed')
    expect(h.undoDesign).not.toHaveBeenCalled()
  })
  it('acknowledges a failed commit and permits a fresh preflight for retry', async () => {
    const h = await harness(); h.api.createSweep.mockResolvedValue(null)
    expect((await h.controller.handle(h.event)).reason).toBe('commit_failed')
    expect(h.sendFeedback).toHaveBeenLastCalledWith(h.event, 'refused', 'commit_failed', undefined)
  })
  it('retains successful commit and Undo identity when native scene refresh fails', async () => {
    const h = await harness(); h.api.refreshNativeVRScene.mockRejectedValue(new Error('Offline'))
    expect((await h.controller.handle(h.event)).reason).toBe('committed')
    expect(h.sendFeedback.mock.calls.at(-1)[1]).toBe('succeeded')
    expect(h.onOutcome).toHaveBeenLastCalledWith(expect.objectContaining({ reason: 'committed_scene_refresh_failed' }))
    expect((await h.controller.handle({ ...h.event, sequence: 2, action: 'undo' })).accepted).toBe(true)
  })
  it('never mutates before pending acknowledgement or replays after lost terminal acknowledgement', async () => {
    const first = await harness(); first.sendFeedback.mockResolvedValue(null)
    expect((await first.controller.handle(first.event)).reason).toBe('execution_failed')
    expect(first.api.createSweep).not.toHaveBeenCalled()
    const second = await harness(); second.sendFeedback.mockResolvedValueOnce({ published: true }).mockResolvedValueOnce(null)
    expect((await second.controller.handle(second.event)).reason).toBe('acknowledgement_failed')
    await second.controller.handle(second.event)
    expect(second.api.createSweep).toHaveBeenCalledTimes(1)
  })
})

it('carries full point orientations and advisory geometry through preflight without blocking commit', async () => {
  const raw = {...draft(), orientations_deg: [null,[15,30,45],[0,90,0]]}
  const api = { currentRevisionWatermark:()=>4, previewSweep: vi.fn(async()=>({
    length_nm:21, revision:4, origin_nm:[5,0,0], path_nm:[[5,0,0],[5,0,10]],
    helix_paths_nm:[[[6,0,0],[6,0,10]]], point_bases:[[[1,0,0],[0,1,0],[0,0,1]]],
    feasibility:{status:'warning',warning_segments:[0],message:'Bend exceeds limit'},
  })) }
  const sendFeedback = vi.fn(async()=>({published:true}))
  const coordinator = createVRToolPreflightCoordinator({sendFeedback})
  await coordinator.request(9,raw,{design:design(),api})
  expect(sendFeedback.mock.lastCall[0]).toMatchObject({status:'warn',sweep_preview:{path:[[0,0,0],[0,0,10]],warning_segments:[0]}})
  expect(coordinator.takeValidatedPlan(9).commit.arguments.orientations_deg).toEqual(raw.orientations_deg)
  expect(normalizeVRToolConfig({...raw,orientations_deg:[null]})).toBeNull()
  expect(normalizeVRToolConfig({...raw,orientations_deg:[null,[0,NaN,0],null]})).toBeNull()
})

it('starts Sweep export before desktop sync and preserves acknowledgement ordering', async () => {
  const h = await harness()
  let finishSync, finishExport
  h.api.refreshNativeVRScene.mockImplementation(() => new Promise(resolve => { finishExport = resolve }))
  h.api.createSweep.mockImplementation(async (args, { onCommitted }) => {
    onCommitted({ design: h.state.currentDesign, revision: 5 })
    await new Promise(resolve => { finishSync = resolve })
    h.state.currentDesign.feature_log.push({ id: 'sweep-entry' })
    return { vr_transaction: { feature_log_entry_id: 'sweep-entry', target_count: 2 } }
  })
  const done = h.controller.handle(h.event)
  await vi.waitFor(() => expect(h.api.refreshNativeVRScene).toHaveBeenCalledOnce())
  expect(h.sendFeedback.mock.calls.map(call => call[1])).toEqual(['pending'])
  finishSync(); await Promise.resolve()
  expect(h.sendFeedback.mock.calls.map(call => call[1])).toEqual(['pending'])
  finishExport({ published: true })
  expect((await done).accepted).toBe(true)
  expect(h.sendFeedback.mock.calls.map(call => call[1])).toEqual(['pending', 'succeeded'])
  expect(h.api.refreshNativeVRScene).toHaveBeenCalledOnce()
})
