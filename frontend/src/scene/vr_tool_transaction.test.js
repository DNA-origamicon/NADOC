import { describe, expect, it, vi } from 'vitest'

import {
  createVRToolTransactionCoordinator,
  featureLogTailId,
} from './vr_tool_transaction.js'

describe('native VR tool transaction coordinator', () => {
  it('captures an exact committed feature and undoes only that tail entry', async () => {
    let state = { currentDesign: { feature_log: [] } }
    const undoDesign = vi.fn(async () => {
      state = { currentDesign: { feature_log: [] } }
      return { design: state.currentDesign }
    })
    const coordinator = createVRToolTransactionCoordinator({
      getState: () => state, undoDesign,
    })
    const execute = vi.fn(async () => {
      state = { currentDesign: { feature_log: [{ id: 'vr-edit-1' }] } }
      return {
        accepted: true,
        result: { vr_transaction: {
          feature_log_entry_id: 'vr-edit-1', target_count: 12,
        } },
      }
    })

    await expect(coordinator.commit({
      tool: 'move_rotate', targetKey: '["domain","d1"]', execute,
    })).resolves.toMatchObject({
      accepted: true,
      reason: 'committed',
      transaction: { featureLogEntryId: 'vr-edit-1', targetCount: 12 },
    })
    await expect(coordinator.undo({ tool: 'move_rotate' })).resolves.toMatchObject({
      accepted: true, reason: 'undone',
    })
    expect(undoDesign).toHaveBeenCalledOnce()
    expect(coordinator.snapshot().committed).toBeNull()
  })

  it('refuses stale undo after an unrelated desktop edit', async () => {
    let state = { currentDesign: { feature_log: [] } }
    const undoDesign = vi.fn()
    const coordinator = createVRToolTransactionCoordinator({
      getState: () => state, undoDesign,
    })
    await coordinator.commit({
      tool: 'move_rotate', targetKey: 'target', execute: async () => {
        state = { currentDesign: { feature_log: [{ id: 'vr-edit' }] } }
        return {
          accepted: true,
          result: { vr_transaction: {
            feature_log_entry_id: 'vr-edit', target_count: 1,
          } },
        }
      },
    })
    state = { currentDesign: { feature_log: [{ id: 'vr-edit' }, { id: 'desktop-edit' }] } }

    await expect(coordinator.undo({ tool: 'move_rotate' })).resolves.toEqual({
      accepted: false, reason: 'undo_stale_desktop_changed',
    })
    expect(undoDesign).not.toHaveBeenCalled()
    expect(coordinator.snapshot().committed).toBeNull()
  })

  it('rejects duplicate execution and unresolved transaction identity', async () => {
    let state = { currentDesign: { feature_log: [] } }
    let release
    const pending = new Promise(resolve => { release = resolve })
    const coordinator = createVRToolTransactionCoordinator({ getState: () => state })
    const first = coordinator.commit({
      tool: 'move_rotate', targetKey: 'target', execute: () => pending,
    })
    await expect(coordinator.commit({
      tool: 'move_rotate', targetKey: 'target', execute: vi.fn(),
    })).resolves.toEqual({ accepted: false, reason: 'transaction_busy' })
    release({
      accepted: true,
      result: { vr_transaction: {
        feature_log_entry_id: 'missing-tail', target_count: 1,
      } },
    })
    await expect(first).resolves.toEqual({
      accepted: false, reason: 'transaction_identity_unresolved',
    })
  })

  it('reads only the canonical feature-log tail identity', () => {
    expect(featureLogTailId({ currentDesign: { feature_log: [{ id: 'a' }, { id: 'b' }] } }))
      .toBe('b')
    expect(featureLogTailId({})).toBeNull()
  })
})
