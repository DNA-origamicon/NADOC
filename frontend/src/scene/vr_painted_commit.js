/** Shared browser executor for revision-pinned painted and end extrusion intents. */
export function createVRPaintedCommit({ preflight, transaction, api, getState, sendFeedback, resolveTarget = () => null, onOutcome = () => {} }) {
  let sequence = 0
  let busy = false
  async function acknowledge(...args) {
    const result = await sendFeedback(...args)
    if (result?.published !== true) throw new Error("feedback_not_published")
  }
  async function run(event) {
    if (event.sequence <= sequence) return { accepted: false, reason: 'invalid_or_stale' }
    sequence = event.sequence
    if (busy) return { accepted: false, reason: 'transaction_busy' }
    if (event.action === 'cancel') {
      preflight.cancel()
      return { accepted: true, reason: 'cancelled' }
    }
    busy = true
    let outcome
    try {
      if (event.action === 'undo') {
        await acknowledge(event, 'pending', 'undoing')
        outcome = await transaction.undo({ tool: 'extrude' })
      } else {
        const plan = preflight.takeValidatedPlan(event.configSequence)
        const args = plan?.commit?.arguments
        const end = event.targetKind === 'end'
        const method = end ? 'addBundleContinuation' : 'addFrameExtrusion'
        const target = end ? resolveTarget({ identity:event.targetIdentity,
          selectionKind:event.targetKind, ownerTokens:event.targetOwnerTokens }) : null
        const sameOwners = values => JSON.stringify(values) === JSON.stringify(event.targetOwnerTokens)
        if (plan?.kind !== (end ? 'extrude_continuation' : 'extrude_frame') || plan.commit.apiMethod !== method) {
          outcome = { accepted: false, reason: 'validated_draft_required' }
        } else if (end && (plan.targetIdentity !== event.targetIdentity ||
                   !sameOwners(plan.targetOwnerTokens) || target?.identity !== event.targetIdentity ||
                   target.selectionKind !== 'end' || !sameOwners(target.ownerTokens))) {
          outcome = { accepted:false, reason:'stale_target' }
        } else if ((end ? args.expectedDesignId : args.expected_design_id) !== getState()?.currentDesign?.id ||
                   (end ? args.expectedRevision : args.expected_revision) !== api.currentRevisionWatermark()) {
          outcome = { accepted: false, reason: 'document_changed' }
        } else {
          await acknowledge(event, 'pending', 'committing')
          outcome = await transaction.commit({
            tool: 'extrude', targetKey: plan.targetIdentity,
            targetIdentity: event.targetIdentity, targetKind: event.targetKind,
            execute: async () => {
              const result = await api[method](args)
              return { accepted: !!result, reason: result ? 'committed' : 'commit_failed', result }
            },
          })
        }
      }
      if (outcome.accepted) {
        const refreshed = await api.refreshNativeVRScene({
          expected_design_id: getState().currentDesign.id,
          expected_revision: api.currentRevisionWatermark(),
        })
        if (!refreshed?.published) {
          onOutcome({ accepted: false, reason: 'committed_scene_refresh_failed' })
        }
      }
      await acknowledge(event, outcome.accepted ? 'succeeded'  : 'refused', outcome.reason, outcome.transaction)
      onOutcome(outcome)
      return outcome
    } catch {
      // A lost terminal acknowledgement must never trigger a second mutation.
      const failure = { accepted: false, reason: outcome?.accepted ? 'acknowledgement_failed' : 'execution_failed' }
      onOutcome(failure)
      return failure
    } finally { busy = false }
  }
  return {
    handle(event) {
      const validTarget = event?.targetKind === 'none'
        ? !event.targetIdentity && !event.targetOwnerTokens?.length
        : event?.targetKind === 'end' && typeof event.targetIdentity === 'string' &&
          !!event.targetIdentity && Array.isArray(event.targetOwnerTokens) && event.targetOwnerTokens.length > 0
      if (event?.mode !== 'extrude' || !validTarget || !['confirm','undo','cancel'].includes(event.action) ||
          !Number.isSafeInteger(event.sequence) || event.sequence < 1) return null
      return run(event)
    },
    reset() { if (!busy) sequence = 0 },
  }
}
