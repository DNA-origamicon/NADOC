/** Only acknowledge history bodies the client actually holds, including children. */
export function hasCompleteSeekHistory(design) {
  if (!design) return false
  return (design.feature_log ?? []).every(entry => {
    if (!entry.evicted) {
      if (entry.feature_type === 'snapshot' && (!entry.design_snapshot_gz_b64 || !entry.post_state_gz_b64)) return false
      if (entry.feature_type === 'routing-cluster' && (!entry.pre_state_gz_b64 || !entry.post_state_gz_b64)) return false
    }
    return (entry.children ?? []).every(child =>
      ['diff_added_b64', 'diff_removed_b64', 'diff_modified_b64'].every(key => child[key] !== '1'))
  })
}

function bodies(design) {
  const values = []
  for (const entry of design.feature_log ?? []) {
    values.push(entry.id, entry.design_snapshot_gz_b64, entry.pre_state_gz_b64, entry.post_state_gz_b64,
      entry.children?.length ?? 0)
    for (const child of entry.children ?? []) {
      values.push(child.id, child.diff_added_b64, child.diff_removed_b64, child.diff_modified_b64)
    }
  }
  return values
}

/** A partial GET can advance the design revision without refreshing cached bodies.
 * Only a successfully applied seek proves these bodies at a specific revision.
 * Keep references to immutable strings, not a copy/hash of megabytes of history.
 */
export function createSeekHistoryAcknowledgement() {
  let verified = null
  return {
    reset() { verified = null },
    acknowledge(design, revision, scope) {
      verified = hasCompleteSeekHistory(design) && Number.isFinite(revision)
        ? { id: design.id, revision, scope, values: bodies(design) } : null
    },
    knownRevision(design, scope) {
      if (!verified || verified.id !== design?.id || verified.scope !== scope) return null
      const values = bodies(design)
      return values.length === verified.values.length && values.every((value, i) => value === verified.values[i])
        ? verified.revision : null
    },
  }
}
