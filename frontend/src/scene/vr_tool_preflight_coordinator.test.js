import { describe, expect, it, vi } from 'vitest'
import { createVRToolPreflightCoordinator } from './vr_tool_preflight_coordinator.js'

const draft = overrides => ({
  mode: 'extrude', target_identity: 'nuc:end', target_kind: 'end',
  target_owner_tokens: ['owner:end'], length_bp: 7, direction_sign: 1,
  strand_filter: 'both', ligate_adjacent: true, footprint_state: 'unresolved',
  ...overrides,
})

const result = (sequence, status = 'ok') => ({
  feedback: {
    tool_config_sequence: sequence,
    target_identity: 'nuc:end', target_kind: 'end', tool_mode: 'extrude',
    status, reason: status === 'ok' ? 'validated' : 'backend_block',
  },
  plan: { kind: 'extrude_continuation' },
})

function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

describe('native VR preflight coordinator', () => {
  it('suppresses a late result and sequences WAITING before the newest verdict', async () => {
    const first = deferred()
    const second = deferred()
    const evaluate = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
    const sent = []
    const coordinator = createVRToolPreflightCoordinator({
      evaluate, sendFeedback: async feedback => { sent.push(feedback) },
    })

    const oldRequest = coordinator.request(4, draft(), {})
    const newRequest = coordinator.request(4, draft({ length_bp: 8 }), {}, {
      waitingReason: 'design_changed',
    })
    second.resolve(result(4))
    await newRequest
    first.resolve(result(4, 'block'))
    expect(await oldRequest).toEqual({ sent: false, reason: 'superseded' })

    expect(sent.map(item => [item.preflight_sequence, item.status, item.reason])).toEqual([
      [1, 'waiting', 'design_changed'],
      [2, 'ok', 'validated'],
    ])
    expect(coordinator.feedbackSequence()).toBe(2)
  })

  it('invalidates an in-flight result on cancel', async () => {
    const pending = deferred()
    const sendFeedback = vi.fn()
    const coordinator = createVRToolPreflightCoordinator({
      evaluate: () => pending.promise, sendFeedback,
    })
    const request = coordinator.request(9, draft(), {})
    coordinator.cancel()
    pending.resolve(result(9))
    expect(await request).toEqual({ sent: false, reason: 'superseded' })
    expect(sendFeedback).not.toHaveBeenCalled()
  })

  it('rebases only a current final verdict after reconnecting to a higher sequence', async () => {
    const sent = []
    const coordinator = createVRToolPreflightCoordinator({
      evaluate: async sequence => result(sequence),
      sendFeedback: async feedback => {
        sent.push(feedback)
        return feedback.preflight_sequence < 41
          ? { published: false, current_preflight_sequence: 40 }
          : { published: true, current_preflight_sequence: feedback.preflight_sequence }
      },
    })
    expect((await coordinator.request(12, draft(), {}, {
      waitingReason: 'design_changed',
    })).sent).toBe(true)
    expect(sent.map(item => [item.preflight_sequence, item.status])).toEqual([
      [1, 'waiting'], [2, 'ok'], [41, 'ok'],
    ])
    expect(coordinator.feedbackSequence()).toBe(41)
  })

  it('refuses malformed drafts without evaluating or publishing', async () => {
    const evaluate = vi.fn()
    const sendFeedback = vi.fn()
    const coordinator = createVRToolPreflightCoordinator({ evaluate, sendFeedback })
    expect(await coordinator.request(1, draft({ length_bp: -1 }), {})).toEqual({
      sent: false, reason: 'invalid_request',
    })
    expect(evaluate).not.toHaveBeenCalled()
    expect(sendFeedback).not.toHaveBeenCalled()
  })

  it('contains synchronous transport failures', async () => {
    const coordinator = createVRToolPreflightCoordinator({
      evaluate: async sequence => result(sequence),
      sendFeedback: () => { throw new Error('offline') },
    })
    expect(await coordinator.request(3, draft(), {})).toEqual({
      sent: false, reason: 'delivery_failed',
    })
  })
})
