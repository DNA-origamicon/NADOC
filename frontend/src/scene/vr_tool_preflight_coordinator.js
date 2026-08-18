/** Superseding coordinator for native-VR parameterized-tool preflights.
 *
 * Tool-configuration sequence protects one draft from another.  A separate
 * monotonic feedback sequence protects the multiple messages produced for one
 * draft (WAITING, then a final verdict) from network reordering.  No mutation
 * method is accepted or invoked here.
 */
import { normalizeVRToolConfig } from './vr_tool_config.js'
import { evaluateVRToolPreflight } from './vr_tool_execution_plan.js'

function _feedback(config, toolConfigSequence, status, reason) {
  return {
    tool_config_sequence: toolConfigSequence,
    target_identity: config.target_identity,
    target_kind: config.target_kind,
    tool_mode: config.mode,
    status,
    reason,
  }
}

/**
 * Coordinate read-only validators and publish only the newest request's result.
 * `sendFeedback` may resolve out of order; the attached feedback sequence lets
 * the backend/native consumers independently reject older writes.
 */
export function createVRToolPreflightCoordinator({
  evaluate = evaluateVRToolPreflight,
  sendFeedback,
} = {}) {
  if (typeof evaluate !== 'function' || typeof sendFeedback !== 'function') {
    throw new TypeError('VR preflight coordinator requires evaluate and sendFeedback')
  }
  let requestGeneration = 0
  let feedbackSequence = 0

  const publish = async (feedback, generation, { retryStale = false } = {}) => {
    if (!feedback) return Promise.resolve(null)
    let payload = {
      ...feedback,
      preflight_sequence: ++feedbackSequence,
    }
    let response = null
    try {
      response = await sendFeedback(payload)
    } catch {
      response = null
    }
    const currentSequence = response?.current_preflight_sequence
    if (retryStale && response?.published === false &&
        generation === requestGeneration && Number.isSafeInteger(currentSequence) &&
        currentSequence >= payload.preflight_sequence) {
      feedbackSequence = Math.max(feedbackSequence, currentSequence)
      payload = { ...feedback, preflight_sequence: ++feedbackSequence }
      try {
        response = await sendFeedback(payload)
      } catch {
        response = null
      }
    }
    return response
  }

  return Object.freeze({
    async request(toolConfigSequence, draft, environment = {}, {
      waitingReason = null,
    } = {}) {
      const config = normalizeVRToolConfig(draft)
      if (!Number.isSafeInteger(toolConfigSequence) || toolConfigSequence < 1 || !config) {
        return { sent: false, reason: 'invalid_request' }
      }
      const generation = ++requestGeneration
      if (waitingReason) {
        publish(_feedback(
          config, toolConfigSequence, 'waiting', waitingReason,
        ), generation)
      }
      const result = await evaluate(toolConfigSequence, config, environment)
      if (generation !== requestGeneration) {
        return { sent: false, reason: 'superseded' }
      }
      if (!result?.feedback) return { sent: false, reason: 'no_feedback' }
      const delivered = await publish(
        result.feedback, generation, { retryStale: true },
      )
      if (delivered === null) return { sent: false, reason: 'delivery_failed' }
      if (delivered?.published === false) {
        return { sent: false, reason: 'stale_delivery' }
      }
      return { sent: true, reason: 'published', result }
    },

    cancel() {
      requestGeneration += 1
    },

    feedbackSequence() {
      return feedbackSequence
    },
  })
}
