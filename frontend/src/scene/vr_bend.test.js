import { describe, it, expect, vi } from 'vitest'
import { createVRBend } from './vr_bend.js'
import { createVRToolTransactionCoordinator } from './vr_tool_transaction.js'

function setup(mode = 'bend') {
  const state = { currentDesign: { id: 'design', helices: [{ id: 'h', length_bp: 121 }], cluster_transforms: [{ id: 'c', helix_ids: ['h'] }], feature_log: [] }, currentGeometry: [] }
  const config = { sequence: 3, draft: { mode: 'bend', target_identity: 'hit', target_kind: 'cluster', target_owner_tokens: ['owner'], plane_a_bp: 10, plane_b_bp: 110, angle_deg: 90, direction_deg: 30 } }
  if (mode === 'twist') config.draft = { ...config.draft, mode, amount_mode: 'total_degrees', amount: -90 }
  const event = { mode, action: 'confirm', sequence: 1, configSequence: 3, targetIdentity: 'hit', targetKind: 'cluster', targetOwnerTokens: ['owner'] }
  const api = {
    currentRevisionWatermark: () => 4,
    validateDeformation: vi.fn(async () => ({ status: 'ok' })),
    addDeformation: vi.fn(async () => { state.currentDesign.feature_log.push({ id: 'entry' }); return { vr_transaction: { feature_log_entry_id: 'entry', target_count: 1 } } }),
    refreshNativeVRScene: vi.fn(async () => ({ published: true })),
  }
  const feedback = vi.fn(async () => ({ published: true }))
  const transaction = createVRToolTransactionCoordinator({ getState: () => state, undoDesign: async () => { state.currentDesign.feature_log.pop(); return {} } })
  const resolveTarget = vi.fn(() => ({ identity: 'hit', selectionKind: 'cluster', ownerTokens: ['owner'], selectedRef: { kind: 'cluster', id: 'c' } }))
  const bend = createVRBend({ api, getState: () => state, getConfig: () => config, transaction, sendFeedback: feedback,
    resolveTarget,
  })
  return { bend, api, feedback, config, event, state, resolveTarget }
}
const settled = () => new Promise(resolve => setTimeout(resolve, 0))
describe('VR bend desktop executor', () => {
  it('commits curvature, mirrors the scene and undoes exactly one feature', async () => {
    const { bend, api, feedback, event, state } = setup()
    expect(bend.handle(event)).toBe(true); await settled()
    expect(api.addDeformation).toHaveBeenCalledWith('bend', 10, 110, { kind: 'bend', curvature_deg_per_bp: .9, direction_deg: 30 }, ['h'], false, [], { expectedDesignId: 'design', expectedRevision: 4, targets: [{ kind: 'cluster', id: 'c' }] })
    expect(api.refreshNativeVRScene).toHaveBeenCalledOnce()
    expect(feedback.mock.calls.at(-1)[1]).toBe('succeeded')
    bend.handle(event); await settled();expect(api.addDeformation).toHaveBeenCalledOnce()
    bend.handle({ ...event, sequence: 2, action: 'undo' });await settled()
    expect(state.currentDesign.feature_log).toEqual([])
    expect(feedback.mock.calls.at(-1)[2]).toBe('undone')
  })
  it('refuses stale config, backend blocks and stale desktop history', async () => {
    const s = setup()
    s.bend.handle({ ...s.event, configSequence: 2 }); await settled()
    expect(s.api.addDeformation).not.toHaveBeenCalled()
    s.api.validateDeformation.mockResolvedValue({ status: 'block' })
    s.bend.handle({ ...s.event, sequence: 2 }); await settled()
    expect(s.api.addDeformation).not.toHaveBeenCalled()
    s.api.validateDeformation.mockResolvedValue({ status: 'ok' })
    s.bend.handle({ ...s.event, sequence: 3 }); await settled()
    s.state.currentDesign.feature_log.push({ id: 'desktop-edit' })
    s.bend.handle({ ...s.event, sequence: 4, action: 'undo' }); await settled()
    expect(s.feedback.mock.calls.at(-1)[2]).toBe('undo_stale_desktop_changed')
  })
  it('rechecks revision after asynchronous validation', async () => {
    const s = setup()
    let revision = 4
    s.api.currentRevisionWatermark = () => revision
    s.api.validateDeformation.mockImplementation(async () => { revision++; return { status: 'ok' } })
    s.bend.handle(s.event);await settled()
    expect(s.api.addDeformation).not.toHaveBeenCalled()
    expect(s.feedback.mock.calls.at(-1)[2]).toBe('document_changed')
  })
})

describe('VR twist desktop executor', () => {
  it('commits signed twist and undoes its exact feature entry', async () => {
    const s = setup('twist')
    expect(s.bend.handle(s.event)).toBe(true); await settled()
    expect(s.api.addDeformation.mock.calls[0].slice(0,4)).toEqual(['twist',10,110,{ total_degrees: -90 }])
    expect(s.feedback.mock.calls.at(-1)[1]).toBe('succeeded')
    s.bend.handle({ ...s.event, sequence: 2, action: 'undo' });await settled()
    expect(s.state.currentDesign.feature_log).toEqual([])
    expect(s.feedback.mock.calls.at(-1)[2]).toBe('undone')
  })
  it('rejects a bend draft attached to a twist event', async () => {
    const s = setup()
    s.bend.handle({ ...s.event, mode: 'twist' });await settled()
    expect(s.api.addDeformation).not.toHaveBeenCalled()
  })
})

for (const phase of ['validation', 'acknowledgement']) it(`refuses a changed selection during ${phase}`, async () => {
  const s = setup()
  if (phase === 'validation') s.api.validateDeformation.mockImplementation(async () => {
    s.resolveTarget.mockReturnValue(null)
    return { status: 'ok' }
  })
  else s.feedback.mockImplementation(async () => {
    s.resolveTarget.mockReturnValue(null)
    return { published: true }
  })
  s.bend.handle(s.event); await settled()
  expect(s.api.addDeformation).not.toHaveBeenCalled()
  expect(s.feedback.mock.calls.at(-1)[1]).toBe('refused')
})
