import { buildVRParameterizedToolPlan } from './vr_tool_execution_plan.js'

/** Serialize native bend commits through the desktop deformation/feature log. */
export function createVRBend({ api, getState, getConfig, resolveTarget, transaction, sendFeedback, onError = () => {} }) {
  let sequence = 0
  let busy = false
  async function run(event) {
    if (event.sequence <= sequence) return
    sequence = event.sequence
    if (busy) return
    if (['activate', 'cancel', 'preview'].includes(event.action)) return
    busy = true
    let outcome
    try {
      if (event.action === 'undo') {
        await sendFeedback(event, 'pending', 'undoing')
        outcome = await transaction.undo({ tool: 'bend' })
      } else {
        const config = getConfig()
        const target = resolveTarget({ identity: event.targetIdentity, selectionKind: event.targetKind, ownerTokens: event.targetOwnerTokens })
        const state = getState()
        const revision = api.currentRevisionWatermark()
        const described = buildVRParameterizedToolPlan(config.draft, { toolTarget: target, design: state.currentDesign, geometry: state.currentGeometry })
        if (event.configSequence !== config.sequence || !described.accepted || config.draft?.mode !== 'bend') {
          outcome = { accepted: false, reason: 'stale_target' }
        } else {
          const plan = described.plan
          const verdict = await api.validateDeformation(plan.preflight.arguments)
          if (!['ok', 'warn'].includes(verdict?.status)) outcome = { accepted: false, reason: 'backend_block' }
          else if (api.currentRevisionWatermark() !== revision || getConfig().sequence !== config.sequence) {
            outcome = { accepted: false, reason: 'document_changed' }
          } else {
            const ack = await sendFeedback(event, 'pending', 'committing')
            if (ack?.published !== true) throw new Error('Bend acknowledgement was not published')
            outcome = await transaction.commit({ tool: 'bend', targetKey: JSON.stringify([event.targetIdentity, event.targetOwnerTokens]),
              targetIdentity: event.targetIdentity, targetKind: event.targetKind,
              execute: async () => {
                const result = await api.addDeformation(...plan.commit.arguments, { expectedDesignId: state.currentDesign.id, expectedRevision: revision })
                return { accepted: !!result, result }
              },
            })
          }
        }
      }
      if (outcome.accepted) {
        try {
          const refreshed = await api.refreshNativeVRScene({ expected_design_id: getState().currentDesign.id, expected_revision: api.currentRevisionWatermark() })
          if (!refreshed?.published) onError('Bend saved; VR scene refresh failed.')
        } catch { onError('Bend saved; VR scene refresh failed.') }
      }
      await sendFeedback(event, outcome.accepted ? 'succeeded' : 'refused', outcome.reason, outcome.transaction)
      if (!outcome.accepted) onError(`VR Bend: ${outcome.reason.replaceAll('_', ' ')}`)
    } catch (error) {
      onError(error.message)
      if (!outcome?.accepted) await sendFeedback(event, 'failed', 'execution_failed').catch(() => {})
    } finally { busy = false }
  }
  return {
    reset() { if (!busy) sequence = 0 },
    handle(event) {
      if (event?.mode !== 'bend' || !Number.isSafeInteger(event.sequence) || event.sequence < 1 ||
          !['activate', 'preview', 'confirm', 'cancel', 'undo'].includes(event.action)) return false
      void run(event)
      return true
    },
  }
}
