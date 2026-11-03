import { createVRCommitRefresh } from './vr_commit_refresh.js'
/** Native Sweep intents execute through the same feature log as desktop Sweep. */
export function createVRSweepCommit({ preflight, transaction, api, getState, sendFeedback, onOutcome = () => {} }) {
  let sequence = 0
  let busy = false
  let edited = null
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
    const sceneRefresh = createVRCommitRefresh({ api, getState })
    let outcome
    try {
      if (event.action === 'undo') {
        await acknowledge(event, 'pending', 'undoing')
        if (edited) {
          if (edited.design !== getState()?.currentDesign || edited.revision !== api.currentRevisionWatermark()) {
            outcome = { accepted: false, reason: 'undo_stale_desktop_changed' }; edited = null
          } else {
            const result = await api.undo({ onCommitted: sceneRefresh.onCommitted, deferGeometry: true })
            outcome = { accepted: !!result, reason: result ? 'undone' : 'undo_failed', transaction: edited.transaction }
            if (result) edited = null
          }
        } else outcome = await transaction.undo({ tool: 'sweep', onCommitted: sceneRefresh.onCommitted, deferGeometry: true })
      } else {
        const plan = preflight.takeValidatedPlan(event.configSequence)
        const args = plan?.commit?.arguments
        if (plan?.kind !== 'sweep' || !['createSweep', 'editFeature'].includes(plan.commit.apiMethod)) {
          outcome = { accepted: false, reason: 'validated_draft_required' }
        } else if (args.expected_design_id !== getState()?.currentDesign?.id ||
                   args.expected_revision !== api.currentRevisionWatermark()) {
          outcome = { accepted: false, reason: 'document_changed' }
        } else if (plan.commit.apiMethod === 'editFeature') {
          const reference = plan.editReference
          const entry = getState()?.currentDesign?.feature_log?.[reference?.index]
          if (!entry || entry.id !== reference.feature_id || reference.revision !== api.currentRevisionWatermark()) {
            outcome = { accepted: false, reason: 'sweep_edit_stale' }
          } else {
            await acknowledge(event, 'pending', 'committing')
            const result = await api.editFeature(reference.index, args, { onCommitted: sceneRefresh.onCommitted, deferGeometry: true })
            const token = { targetIdentity: null, targetKind: 'none', featureLogEntryId: entry.id }
            outcome = { accepted: !!result, reason: result ? 'committed' : 'commit_failed', transaction: token }
            if (result) { transaction.clear(); edited = { design: getState().currentDesign, revision: api.currentRevisionWatermark(), transaction: token } }
          }
        } else {
          edited = null
          await acknowledge(event, 'pending', 'committing')
          outcome = await transaction.commit({ tool: 'sweep', targetKey: plan.targetIdentity,
            targetIdentity: null, targetKind: 'none', execute: async () => {
              const result = await api.createSweep(args, { onCommitted: sceneRefresh.onCommitted, deferGeometry: true })
              return { accepted: !!result, reason: result ? 'committed' : 'commit_failed', result }
            } })
        }
      }
      // Publish the terminal verdict even if scene refresh fails after a commit.
      // The exact feature token still permits Undo; replay must never create DNA twice.
      let refreshFailed = false
      if (outcome.accepted) {
        try {
          const response = await sceneRefresh.complete()
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
    reset() { if (!busy) { sequence = 0; edited = null } },
  }
}
