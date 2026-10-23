import { createContextMenu } from './primitives/context_menu.js'
import { showFeatureDependencies } from './primitives/feature_dependencies_dialog.js'
import { showFeatureReorder, showFeatureSuppression } from './primitives/feature_reorder_dialog.js'
import { showPersistentToast } from './toast.js'

/** Secondary history actions share the existing dialogs and publication lifecycle. */
export function createFeatureLogContextMenu({ store, api }) {
  let menu = null
  const close = () => { menu?.close(); menu = null }

  function bind(row, source, rowIndex) {
    if (!api.partRepairAPI && !api.getFeatureDependencies) return
    const current = () => row.isConnected && store.getState().currentDesign === source
      && !store.getState().assemblyActive
    const run = action => async () => {
      if (!current()) return
      try { await action() } catch (error) { showPersistentToast(error.message) }
    }
    const open = (x, y) => {
      close()
      if (!current()) return
      const items = []
      if (api.partRepairAPI) {
        items.push({ label: source.feature_log[rowIndex].suppressed ? 'Unsuppress' : 'Suppress',
          onClick: run(() => showFeatureSuppression({ store, api, source, rowIndex })) })
        if (source.feature_log.length > 1) items.push({ label: 'Move…',
          onClick: run(() => showFeatureReorder({ store, api, source, rowIndex })) })
      }
      if (api.getFeatureDependencies) items.push({ label: 'View dependencies', onClick: run(async () => {
        const graph = await api.getFeatureDependencies()
        if (current()) showFeatureDependencies({ graph, rowIndex, store, source })
      }) })
      menu = createContextMenu({ x, y, items })
      menu.root.setAttribute('aria-label', `F${rowIndex + 1} actions`)
    }
    row.tabIndex = 0
    row.setAttribute('aria-haspopup', 'menu')
    row.addEventListener('contextmenu', event => {
      event.preventDefault(); event.stopPropagation()
      open(event.clientX, event.clientY)
    })
    row.addEventListener('keydown', event => {
      if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
      event.preventDefault(); event.stopPropagation()
      const rect = row.getBoundingClientRect()
      open(rect.left, rect.bottom)
    })
  }
  return { bind, close }
}
