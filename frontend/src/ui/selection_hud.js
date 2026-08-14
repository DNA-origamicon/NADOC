/** Maintains the persistent multi-selection summary shown over the viewport. */
export function initSelectionHud({ store, selectionManager, selectedCrossoverRefs }) {
  const element = document.getElementById('selection-count-hud')

  function update() {
    if (!element) return
    const state = store.getState()
    const refs = state.selection?.items ?? []
    const counts = [
      [refs.filter(ref => ref.kind === 'strand').length, 'strand'],
      [refs.filter(ref => ref.kind === 'domain').length, 'domain'],
      [(selectionManager.getMultiOverhangs?.() ?? []).length, 'overhang'],
      [selectedCrossoverRefs(state).length, 'crossover'],
      [refs.filter(ref => ref.kind === 'end').length, 'end'],
      [selectionManager.getCtrlBeads?.().length ?? 0, 'bead'],
    ]
    const parts = counts
      .filter(([count]) => count > 0)
      .map(([count, label]) => `${count} ${label}${count === 1 ? '' : 's'}`)
    if (!parts.length) {
      element.style.display = 'none'
      return
    }
    element.textContent = `${parts.join(' · ')} selected`
    element.style.display = 'flex'
  }

  const unsubscribe = store.subscribe((next, previous) => {
    if (next.selection !== previous.selection) update()
  })
  return { update, dispose: unsubscribe }
}
