import { it, expect, vi } from 'vitest'
import { createVRPaintedCommit } from './vr_painted_commit.js'
import { createVRToolTransactionCoordinator } from './vr_tool_transaction.js'

function harness(end = false) {
  const state = { currentDesign: { id: 'doc', feature_log: [] } }
  const api = { refreshNativeVRScene: vi.fn(async () => ({ published: true })), currentRevisionWatermark: () => 3, addFrameExtrusion: vi.fn(async () => {
    state.currentDesign.feature_log.push({ id: 'edit' })
    return { vr_transaction: { feature_log_entry_id: 'edit', target_count: 2 } }
  }) }
  const plan = { kind: 'extrude_frame', targetIdentity: 'document:doc',
    commit: { apiMethod: 'addFrameExtrusion', arguments: { expected_design_id: 'doc', expected_revision: 3 } } }
  const preflight = { takeValidatedPlan: vi.fn().mockReturnValueOnce(plan), cancel: vi.fn() }
  const undoDesign = vi.fn(async () => { state.currentDesign.feature_log.pop(); return {} })
  const transaction = createVRToolTransactionCoordinator({ getState: () => state, undoDesign })
  const sendFeedback = vi.fn(async () => ({ published: true }))
  const controller = createVRPaintedCommit({ preflight, transaction, api, getState: () => state, sendFeedback })
  const event = { mode: 'extrude', action: 'confirm', targetKind: 'none', targetIdentity: null, targetOwnerTokens: [], sequence: 1, configSequence: 7 }
  const target = { identity:'nuc:end', selectionKind:'end', ownerTokens:['owner:end'] }
  if (end) {
    api.addBundleContinuation = api.addFrameExtrusion
    plan.kind = 'extrude_continuation'; plan.targetIdentity = target.identity
    plan.targetOwnerTokens = [...target.ownerTokens]
    plan.commit = { apiMethod:'addBundleContinuation', arguments:{ expectedDesignId:'doc',expectedRevision:3 } }
    Object.assign(event,{ targetKind:'end',targetIdentity:target.identity,targetOwnerTokens:[...target.ownerTokens] })
  }
  const endController = end ? createVRPaintedCommit({ preflight,transaction,api,getState:()=>state,
    sendFeedback,resolveTarget:()=>target }) : controller
  return { controller:endController, api, event, state, sendFeedback, preflight, undoDesign, plan, target }
}
it('commits once and binds Undo to the actual feature entry', async () => {
  const h = harness()
  expect((await h.controller.handle(h.event)).accepted).toBe(true)
  expect(h.preflight.takeValidatedPlan).toHaveBeenCalledWith(7)
  expect((await h.controller.handle(h.event)).reason).toBe('invalid_or_stale')
  expect(h.api.addFrameExtrusion).toHaveBeenCalledTimes(1)
  expect((await h.controller.handle({ ...h.event, sequence: 2, action: 'undo' })).accepted).toBe(true)
  expect(h.undoDesign).toHaveBeenCalledTimes(1)
})
it('refuses a changed document without invoking mutation', async () => {
  const h = harness(); h.state.currentDesign.id = 'different'
  expect((await h.controller.handle(h.event)).reason).toBe('document_changed')
  expect(h.api.addFrameExtrusion).not.toHaveBeenCalled()
})
it('requires successful pending delivery before mutation', async () => {
  const h = harness(); h.sendFeedback.mockResolvedValue(null)
  expect((await h.controller.handle(h.event)).reason).toBe('execution_failed')
  expect(h.api.addFrameExtrusion).not.toHaveBeenCalled()
})
it('does not retry a committed edit when the terminal acknowledgement fails', async () => {
  const h = harness(); h.sendFeedback.mockResolvedValueOnce({ published: true }).mockResolvedValueOnce(null)
  expect((await h.controller.handle(h.event)).reason).toBe('acknowledgement_failed')
  await h.controller.handle(h.event)
  expect(h.api.addFrameExtrusion).toHaveBeenCalledTimes(1)
})
it('refuses undo after an unrelated desktop edit', async () => {
  const h = harness(); await h.controller.handle(h.event)
  h.state.currentDesign.feature_log.push({ id: 'desktop' })
  expect((await h.controller.handle({ ...h.event, sequence: 2, action: 'undo' })).reason).toBe('undo_stale_desktop_changed')
  expect(h.undoDesign).not.toHaveBeenCalled()
})

it('shares end commit, scene refresh and feature-bound Undo without replay', async () => {
  const h = harness(true)
  expect((await h.controller.handle(h.event)).accepted).toBe(true)
  expect(h.api.addBundleContinuation).toHaveBeenCalledTimes(1)
  expect(h.api.refreshNativeVRScene).toHaveBeenCalledTimes(1)
  expect((await h.controller.handle(h.event)).reason).toBe('invalid_or_stale')
  expect((await h.controller.handle({ ...h.event,sequence:2,action:'undo' })).accepted).toBe(true)
})
it.each(['identity','owners','revision'])('rejects an end after %s changes', async kind => {
  const h = harness(true)
  if (kind==='identity') h.target.identity='different'
  if (kind==='owners') h.event.targetOwnerTokens=['another-owner']
  if (kind==='revision') h.plan.commit.arguments.expectedRevision=2
  expect((await h.controller.handle(h.event)).accepted).toBe(false)
  expect(h.api.addBundleContinuation).not.toHaveBeenCalled()
})
