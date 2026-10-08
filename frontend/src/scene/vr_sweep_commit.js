/** Native Sweep intents execute through the same feature log as desktop Sweep. */
export function createVRSweepCommit({ preflight, transaction, api, getState, sendFeedback, onOutcome = () => {} }) {
  let sequence = 0
  let busy = false
  async function acknowledge(event, status, reason, committed) {
    const response = await sendFeedback(event, status, reason, committed)
    if (response?.published !== true) throw new Error('feedback_not_published')
  }
  async function run(event) {
    if (event.sequence <= sequence) return { accepted: false, reason: 'invalid_or_stale' }
    sequence = event.sequence
    if (busy) return { accepted: false, reason: 'transaction_busy' }
    if (event.action === 'cancel' || event.action === 'activate') {
      preflight.cancel()
      return { accepted: true, reason: event.action === 'cancel' ? 'cancelled' : 'configured' }
    }
    if (event.action === 'preview') return { accepted: true, reason: 'native_preview' }
    busy = true
    let outcome
    try {
      if (event.action === 'undo') {
        await acknowledge(event, 'pending', 'undoing')
        outcome = await transaction.undo({ tool: 'sweep' })
      } else {
        const plan = preflight.takeValidatedPlan(event.configSequence)
        const args = plan?.commit?.arguments
        if (plan?.kind !== 'sweep' || plan.commit.apiMethod !== 'createSweep') {
          outcome = { accepted: false, reason: 'validated_draft_required' }
        } else if (args.expected_design_id !== getState()?.currentDesign?.id ||
                   args.expected_revision !== api.currentRevisionWatermark()) {
          outcome = { accepted: false, reason: 'document_changed' }
        } else {
          await acknowledge(event, 'pending', 'committing')
          outcome = await transaction.commit({ tool: 'sweep', targetKey: plan.targetIdentity,
            targetIdentity: null, targetKind: 'none', execute: async () => {
              const result = await api.createSweep(args)
              return { accepted: !!result, reason: result ? 'committed' : 'commit_failed', result }
            } })
        }
      }
      // Publish the terminal verdict even if scene refresh fails after a commit.
      // The exact feature token still permits Undo; replay must never create DNA twice.
      let refreshFailed = false
      if (outcome.accepted) {
        try {
          const response = await api.refreshNativeVRScene({
            expected_design_id: getState().currentDesign.id,
            expected_revision: api.currentRevisionWatermark(),
          })
          refreshFailed = response?.published !== true
        } catch { refreshFailed = true }
      }
      await acknowledge(event, outcome.accepted ? 'succeeded' : 'refused', outcome.reason, outcome.transaction)
      onOutcome(refreshFailed ? { ...outcome, reason: 'committed_scene_refresh_failed' } : outcome)
      return outcome
    } catch {
      const failure = { accepted: false, reason: outcome?.accepted ? 'acknowledgement_failed' : 'execution_failed' }
      if (!outcome?.accepted) {
        try { await acknowledge(event, 'failed', failure.reason) } catch { /* Native remains unconfirmed. */ }
      }
      onOutcome(failure)
      return failure
    } finally { busy = false }
  }
  return {
    handle(event) {
      if (event?.mode !== 'sweep' || event.targetKind !== 'none' || event.targetIdentity != null ||
          !Array.isArray(event.targetOwnerTokens) || event.targetOwnerTokens.length ||
          !['activate', 'preview', 'confirm', 'undo', 'cancel'].includes(event.action) ||
          !Number.isSafeInteger(event.sequence) || event.sequence < 1) return null
      return run(event)
    },
    reset() { if (!busy) sequence = 0 },
  }
}
