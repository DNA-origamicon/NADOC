/** Transient feedback for a refused rebuild, never part of the saved design. */
export function createFeatureHistoryFeedback(store, events = globalThis.window) {
  const owner = Symbol('history edit')
  let lastError = null, lastSource = null
  function clear() {
    lastError = lastSource = null
    if (store.getState().featureHistoryFailure?.owner === owner)
      store.setState({ featureHistoryFailure: null })
  }
  function update(error, source = store.getState().currentDesign) {
    if (!error || source !== store.getState().currentDesign || store.getState().assemblyActive) { clear(); return }
    if (error === lastError && source === lastSource) return
    const id = error.detail?.feature_id ?? error.detail?.assessment?.issues?.[0]?.feature_id
    const commands = source?.feature_log?.flatMap(row => row.feature_type === 'routing-cluster' && row.children?.length ? row.children : [row]) ?? []
    const index = commands.findIndex(row => row.id === id)
    if (index < 0) { clear(); return }
    lastError = error; lastSource = source
    // Replay stops at the first refusal. The remaining suffix has not been
    // regenerated for this draft; this does not assert a geometric dependency.
    store.setState({ featureHistoryFailure: { owner, source, featureId: id,
      message: error.message, blockedIds: new Set(commands.slice(index + 1).map(row => row.id)) } })
  }
  const unsubscribe = store.subscribe?.(next => {
    if (lastSource && (next.currentDesign !== lastSource || next.assemblyActive)) clear()
  })
  events?.addEventListener?.('nadoc:document-reset', clear)
  return { update, clear, dispose() { clear(); unsubscribe?.(); events?.removeEventListener?.('nadoc:document-reset', clear) } }
}

export function historyFailureStatus(failure, source, entry) {
  if (!failure || failure.source !== source) return null
  const ids = [entry.id, ...(entry.children ?? []).map(child => child.id)]
  if (ids.includes(failure.featureId)) return { state: 'error', text: 'Edit failed',
    reason: `Attempted edit refused: ${failure.message}. The saved part is unchanged.` }
  if (ids.some(id => failure.blockedIds.has(id))) return { state: 'blocked', text: 'Blocked',
    reason: 'Not regenerated for this attempted edit because an earlier feature failed. The saved part is unchanged.' }
  return null
}
