import { confirmedAssemblyRevision } from '../api/assembly_response_authority.js'
import { createContextMenu } from './primitives/context_menu.js'
import { showFeatureDependencies } from './primitives/feature_dependencies_dialog.js'
import { showFeatureReorder, showFeatureSuppression, showFeatureDeletion } from './primitives/feature_reorder_dialog.js'
import { showPersistentToast } from './toast.js'
import { assemblyFeatureFields, editAssemblyHistoryFeature } from './assembly_feature_editor.js'
import { instanceFeatureFields, editInstanceHistoryFeature } from './instance_feature_editor.js'

/** Secondary history actions share the existing dialogs and publication lifecycle. */
export function createFeatureLogContextMenu({ store, api }) {
  let menu = null
  const close = () => { menu?.close(); menu = null }

  function bind(row, source, rowIndex, { assembly = false, instanceId, assemblySource, isTargetCurrent = () => true } = {}) {
    const target = instanceId ? { instanceId, assemblySource, isTargetCurrent } : assembly ? { assembly } : {}
    const transport = assembly || instanceId ? api.assemblyHistoryAPI : api.partRepairAPI
    const dependencies = instanceId ? (api.getAssemblyInstanceFeatureDependencies
      ? () => api.getAssemblyInstanceFeatureDependencies(instanceId) : null)
      : assembly ? api.getAssemblyFeatureDependencies : api.getFeatureDependencies
    if (assembly && source.feature_log[rowIndex].suppressed) {
      const badge = document.createElement('span')
      badge.textContent = 'Suppressed'; badge.dataset.historyStatus = 'suppressed'
      row.append(badge)
    }
    if (!transport && !dependencies) return
    const current = () => row.isConnected && (instanceId ? store.getState().assemblyActive
        && store.getState().currentAssembly === assemblySource && isTargetCurrent()
      : assembly ? store.getState().assemblyActive && store.getState().currentAssembly === source
        : store.getState().currentDesign === source && !store.getState().assemblyActive)
    const run = action => async () => {
      if (!current()) return
      try { await action() } catch (error) { showPersistentToast(error.message) }
    }
    const open = (x, y) => {
      close()
      if (!current()) return
      const items = []
      if (instanceId && transport && instanceFeatureFields(source.feature_log[rowIndex]).length)
        items.push({ label: 'Edit inputs…', onClick: run(() => editInstanceHistoryFeature({ store, api, source, rowIndex, ...target })) })
      if (assembly && transport && assemblyFeatureFields(source.feature_log[rowIndex]).length)
        items.push({ label: 'Edit inputs…', onClick: run(() => editAssemblyHistoryFeature({ store, api, source, rowIndex })) })
      if (transport) {
        items.push({ label: source.feature_log[rowIndex].suppressed ? 'Unsuppress' : 'Suppress',
          onClick: run(() => showFeatureSuppression({ store, api, source, rowIndex, ...target })) })
        if (source.feature_log.length > 1) items.push({ label: 'Move…',
          onClick: run(() => showFeatureReorder({ store, api, source, rowIndex, ...target })) })
        if (instanceId) items.push({ label: 'Delete…', onClick: run(() => showFeatureDeletion({ store, api, source, rowIndex, ...target })) })
      }
      if (dependencies) items.push({ label: 'View dependencies', onClick: run(async () => {
        const graph = await dependencies()
        const parent = instanceId ? assemblySource : source
        if (current() && (!(assembly || instanceId) || (graph.assembly_id === parent.id && graph.revision === confirmedAssemblyRevision(parent)))
            && (!instanceId || (graph.instance_id === instanceId && graph.design_id === source.id)))
          showFeatureDependencies({ graph, rowIndex, store, source, ...(assembly ? { assembly } : {}), ...(instanceId ? { isCurrent: current } : {}) })
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
