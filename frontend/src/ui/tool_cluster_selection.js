import { canonicalSelection, selectedClusterIds } from '../scene/selection_model.js'

function selectedCluster(state) {
  const selection = canonicalSelection(state)
  if (selection.items.some(ref => ref.kind !== 'cluster')) return null
  const ids = selectedClusterIds(state)
  if (!ids.length && state.activeClusterId) ids.push(state.activeClusterId)
  if (ids.length !== 1) return null
  return state.currentDesign?.cluster_transforms?.find(cluster => cluster.id === ids[0]) ?? null
}

/** One-shot cluster picking; finish after the current selection gesture has settled. */
export function beginClusterSelection({ store, selectionManager, onSelected, onCancelled, resolveTarget = selectedCluster }) {
  const designId = store.getState().currentDesign?.id
  const filters = store.getState().selectableTypes
  selectionManager.clearSelection()
  store.setState({ activeClusterId: null, selectableTypes: {
    ...filters, scaffold: true, staples: true, loops: false, skips: false, extensions: false, overhangs: false,
  } })
  selectionManager.setSelectionLevel('cluster')
  let active = true, queued = false
  const finish = () => {
    if (!active) return
    active = false
    unsubscribe()
    selectionManager.setSelectionLevel('default')
    if (filters) store.setState({ selectableTypes: filters })
  }
  const unsubscribe = store.subscribe(() => {
    if (!active || queued) return
    queued = true
    queueMicrotask(() => {
      queued = false
      if (!active) return
      const state = store.getState()
      if (state.assemblyActive || state.currentDesign?.id !== designId || canonicalSelection(state).level !== 'cluster') {
        finish(); onCancelled?.(); return
      }
      const target = resolveTarget(state)
      if (!target) return
      finish()
      // Tool scope owns the picked target now; release the visual selection.
      selectionManager.clearSelection()
      onSelected(target)
    })
  })
  return { cancel: finish }
}
