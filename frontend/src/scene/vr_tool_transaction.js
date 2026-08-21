/** Browser-authoritative lifecycle for one committed native-VR tool edit.
 *
 * The native viewer emits intents; this coordinator serializes execution and
 * binds Undo to the exact feature-log entry returned by the mutation. A later
 * desktop edit makes that token stale instead of letting VR undo unrelated work.
 */

export function featureLogTailId(state) {
  const entries = state?.currentDesign?.feature_log
  return Array.isArray(entries) && entries.length
    ? entries.at(-1)?.id ?? null
    : null
}

function _transactionFrom(outcome) {
  return outcome?.result?.vr_transaction ?? outcome?.vr_transaction ?? null
}

export function createVRToolTransactionCoordinator({
  getState = () => ({}),
  undoDesign = async () => null,
} = {}) {
  let inFlight = false
  let committed = null

  async function commit({
    tool, targetKey, targetIdentity = null, targetKind = null, execute,
  } = {}) {
    if (inFlight) return { accepted: false, reason: 'transaction_busy' }
    if (typeof execute !== 'function' || typeof tool !== 'string' || !tool ||
        typeof targetKey !== 'string' || !targetKey) {
      return { accepted: false, reason: 'invalid_transaction' }
    }
    inFlight = true
    try {
      const outcome = await execute()
      if (!outcome?.accepted) {
        return { accepted: false, reason: outcome?.reason ?? 'commit_failed' }
      }
      const transaction = _transactionFrom(outcome)
      const entryId = transaction?.feature_log_entry_id
      if (typeof entryId !== 'string' || !entryId ||
          featureLogTailId(getState()) !== entryId) {
        return { accepted: false, reason: 'transaction_identity_unresolved' }
      }
      committed = {
        tool,
        targetKey,
        targetIdentity,
        targetKind,
        featureLogEntryId: entryId,
        targetCount: Number(transaction.target_count) || 0,
      }
      return { accepted: true, reason: 'committed', transaction: { ...committed } }
    } catch {
      return { accepted: false, reason: 'commit_failed' }
    } finally {
      inFlight = false
    }
  }

  async function undo({ tool } = {}) {
    if (inFlight) return { accepted: false, reason: 'transaction_busy' }
    if (!committed || committed.tool !== tool) {
      return { accepted: false, reason: 'no_vr_commit' }
    }
    if (featureLogTailId(getState()) !== committed.featureLogEntryId) {
      committed = null
      return { accepted: false, reason: 'undo_stale_desktop_changed' }
    }
    inFlight = true
    try {
      const transaction = { ...committed }
      const result = await undoDesign()
      if (!result) return { accepted: false, reason: 'undo_failed' }
      committed = null
      return { accepted: true, reason: 'undone', transaction }
    } catch {
      return { accepted: false, reason: 'undo_failed' }
    } finally {
      inFlight = false
    }
  }

  function clear() {
    if (inFlight) return false
    committed = null
    return true
  }

  return {
    commit,
    undo,
    clear,
    snapshot: () => ({
      inFlight,
      committed: committed ? { ...committed } : null,
    }),
  }
}
