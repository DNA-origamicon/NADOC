/**
 * Cross-tab coordination for the 3D editor.
 *
 * Owns BroadcastChannel routing, editor discovery, selection mirroring, and
 * same-file co-edit warnings. The composition root supplies live subsystem
 * handles and two getters for state that is established during boot.
 */
import { selectedStrandIds } from '../scene/selection_model.js'
import { countCoeditingSiblings } from '../ui/sync_badge.js'
import { docHeadersFor, getDocId } from '../shared/doc_id.js'

export function initCrossTabSync({
  api,
  assemblyRefresh,
  broadcast,
  getPartEditContext,
  getWorkspacePath,
  lifecycleSync,
  selectionManager,
  showToast,
  store,
  syncBadge,
}) {
  const editorRegistry = new Map()
  const otherTabDocs = new Map()
  let syncingSelection = false
  let lastAnnouncedDesignId = null
  let docClobberWarned = false

  function renderEditorDropdown() {
    const dropdown = document.getElementById('editor-tab-dropdown')
    if (!dropdown) return
    dropdown.replaceChildren()
    if (editorRegistry.size === 0) {
      dropdown.style.display = 'none'
      return
    }
    for (const { windowName, designName } of editorRegistry.values()) {
      const button = document.createElement('button')
      button.className = 'dropdown-item'
      button.textContent = designName || 'Untitled'
      button.addEventListener('click', () => window.open('', windowName)?.focus())
      dropdown.appendChild(button)
    }
    const separator = document.createElement('hr')
    separator.style.cssText = 'border:none;border-top:1px solid #30363d;margin:4px 0'
    dropdown.appendChild(separator)
    const newButton = document.createElement('button')
    newButton.className = 'dropdown-item'
    newButton.textContent = 'Open New Editor ↗'
    newButton.addEventListener('click', () => {
      const query = getDocId() ? `?doc=${encodeURIComponent(getDocId())}` : ''
      window.open(`/cadnano-editor.html${query}`, `nadoc-editor-${Date.now()}`)
    })
    dropdown.appendChild(newButton)
    dropdown.style.display = ''
  }

  function announceDocumentPresence() {
    const state = store.getState()
    const designId = state.currentDesign?.id ?? null
    if (!designId) return
    broadcast.emit('doc-presence', {
      designId,
      docName: state.currentDesign?.metadata?.name ?? null,
      docAssembly: !!state.assemblyActive,
      workspacePath: getWorkspacePath(),
    })
  }

  function refreshCoediting() {
    syncBadge.setSiblingCoediting(
      countCoeditingSiblings(getWorkspacePath(), getDocId(), [...otherTabDocs.values()]),
    )
  }

  function maybeWarnDocClobber(otherId, otherName, otherAssembly) {
    if (docClobberWarned) return
    const state = store.getState()
    const ownId = state.currentDesign?.id ?? null
    if (state.assemblyActive || otherAssembly || !ownId || !otherId || ownId === otherId) return
    docClobberWarned = true
    showToast(
      `Another tab is editing "${otherName ?? 'a different design'}". This backend holds `
      + 'one document at a time — edits from the two tabs may overwrite each other.',
      9000,
    )
  }

  const unsubscribeStore = store.subscribe((newState, previousState = {}) => {
    if (newState.selection !== previousState.selection && !syncingSelection) {
      const strandIds = selectedStrandIds(newState)
      // Design reconciliation rebuilds the canonical selection object even when
      // its strand owners are unchanged. Echoing that rebuild reselects entire
      // connected strands in the cadnano editor after a pencil ligation.
      const previousIds = new Set(selectedStrandIds(previousState))
      const changed = strandIds.length !== previousIds.size
        || strandIds.some(id => !previousIds.has(id))
      if (strandIds.length > 0 && changed) broadcast.emit('selection-changed', { strandIds })
    }
    const designId = newState.currentDesign?.id ?? null
    if (designId !== lastAnnouncedDesignId) {
      lastAnnouncedDesignId = designId
      docClobberWarned = false
      announceDocumentPresence()
    }
  })

  const unsubscribeBroadcast = broadcast.onMessage(async data => {
    const {
      type, strandIds, source, windowName, designName,
      instanceId, designId, docName, docAssembly,
    } = data
    if (type === 'file-saved' && data.path) {
      lifecycleSync.registerSiblingSave(data.path, broadcast.isSameDoc(data))
      return
    }
    if (type === 'doc-presence-request') announceDocumentPresence()
    if (type === 'doc-goodbye') {
      otherTabDocs.delete(source)
      refreshCoediting()
    }
    if (type === 'doc-presence') {
      otherTabDocs.set(source, {
        designId,
        docName,
        docAssembly,
        workspacePath: data.workspacePath ?? null,
        docId: data.docId ?? null,
      })
      refreshCoediting()
      if (broadcast.isSameDoc(data)) maybeWarnDocClobber(designId, docName, docAssembly)
    }
    if (type === 'design-changed') {
      if (!broadcast.isSameDoc(data)) return
      lifecycleSync.markSameDocActivity()
      if (store.getState().assemblyActive) return
      const geometryUnchanged = data.geometry_unchanged === true
      const changedHelixIds = Array.isArray(data.changed_helix_ids)
        ? data.changed_helix_ids.filter(Boolean)
        : []
      const metadataOnly = geometryUnchanged || data.metadata_only === true
      const startedAt = performance.now()
      const mode = geometryUnchanged
        ? 'design-only'
        : changedHelixIds.length ? `design+partial-geometry(${changedHelixIds.length})` : 'design+geometry'
      syncBadge.syncLog('info', 'BC-SYNC-START', `${mode} source=${source?.slice(0, 8) ?? '?'}`)
      console.info(`[cross-tab-sync] start ${mode}`, { source })
      lifecycleSync.setReloadingFromSSE(true)
      try {
        await api.getDesign({ metadataOnly })
        if (!geometryUnchanged) await api.getGeometry(changedHelixIds.length ? changedHelixIds : null)
      } finally {
        lifecycleSync.setReloadingFromSSE(false)
        const elapsedMs = Math.round(performance.now() - startedAt)
        syncBadge.syncLog('info', 'BC-SYNC-END', `${mode} ${elapsedMs}ms`)
        console.info(`[cross-tab-sync] end ${mode} ${elapsedMs}ms`, { source })
      }
    }
    if (type === 'selection-changed') {
      if (!broadcast.isSameDoc(data)) return
      syncingSelection = true
      try {
        selectionManager.setMultiHighlight(strandIds ?? [])
      } finally {
        syncingSelection = false
      }
    }
    if (type === 'editor-announce' || type === 'editor-title-changed') {
      editorRegistry.set(source, { windowName, designName })
      renderEditorDropdown()
    }
    if (type === 'editor-goodbye') {
      editorRegistry.delete(source)
      renderEditorDropdown()
    }
    if (type === 'part-design-updated') {
      syncBadge.syncLog('info', 'BC-RX', `part-design-updated id=${instanceId}`)
      assemblyRefresh.requestRefresh(instanceId, 'broadcast')
      const context = getPartEditContext()
      if (context?.instanceId === instanceId) {
        try {
          const response = await fetch(`/api/assembly/instances/${instanceId}/design`, {
            headers: docHeadersFor(context.assemblyDoc),
          })
          if (response.ok) {
            const body = await response.json()
            if (body?.design) await api.importDesign(JSON.stringify(body.design))
          }
        } catch (error) {
          console.warn('[sync] part-edit re-import failed:', error?.message ?? error)
        }
      }
    }
    if (type === 'session-closed') {
      try { window.close() } catch { /* best-effort */ }
      setTimeout(() => { window.location.href = '/' }, 50)
    }
  })

  broadcast.emit('editor-list-request')
  broadcast.emit('doc-presence-request')
  announceDocumentPresence()

  return {
    announceDocumentPresence,
    refreshCoediting,
    dispose() {
      unsubscribeStore?.()
      unsubscribeBroadcast?.()
    },
  }
}
