// Multi-document tab spawning (extraction #58 from main.js).
//
// The backend keys state by document, and each tab owns a ?doc=<id>. Selecting
// New Part / New Assembly / Open File when this tab already holds content opens
// the new space in its OWN tab so the current work isn't replaced. A "completely
// empty" space (no helices/strands/instances and no feature-log entries) is
// reused in place.

// Pure: does the given store state hold any user content (design or assembly)?
// A space with no helices/strands/instances AND no feature-log entries is empty.
export function spaceHasContent(state) {
  const d = state.currentDesign, a = state.currentAssembly
  const dHas = !!d && (((d.helices?.length ?? 0) > 0) ||
                       ((d.strands?.length ?? 0) > 0) ||
                       ((d.feature_log?.length ?? 0) > 0))
  const aHas = !!a && (((a.instances?.length ?? 0) > 0) ||
                       ((a.feature_log?.length ?? 0) > 0))
  return dHas || aHas
}

export function initDocSpawn({ store, mintDocId }) {
  function hasContent() {
    return spaceHasContent(store.getState())
  }

  // If this tab has content, mint a doc id and open the requested action in a new
  // tab; return true so the caller skips the in-place action. Empty → false.
  async function spawnDocTabIfBusy(actionQuery) {
    if (!hasContent()) return false
    const id = await mintDocId()
    if (!id) return false
    window.open(`/?doc=${encodeURIComponent(id)}&${actionQuery}`, 'nadoc-doc-' + id)
    return true
  }

  return { spaceHasContent: hasContent, spawnDocTabIfBusy }
}
