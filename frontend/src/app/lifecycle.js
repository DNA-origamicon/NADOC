import * as connectionMonitor from '../shared/connection_monitor.js'
import { nadocBroadcast } from '../shared/broadcast.js'

/**
 * Backend connection monitor: status badge + silent restart recovery.
 *
 * Polls /api/health (via the shared connection_monitor). On disconnect the badge
 * goes red; on a server restart (new server_instance_id) the backend's session
 * cache has already restored the live document — we just re-pull it. If the
 * backend came back empty but this tab still holds the design in localStorage,
 * offer to restore from here.
 *
 * First cut of `app/lifecycle.js` (extraction #53). The autosave subscribers and
 * the Library-SSE handler still live inline in main.js (they share the same
 * loop-prevention flags); fold them into this module in a later batch.
 *
 * Deps:
 *   api, store, assemblyRenderer — backend + scene
 *   setSyncStatus, syncLog       — the inline sync-status badge/log helpers
 *   setReloadingFromSSE          — shim writing main.js's `_reloadingFromSSE`
 *                                  loop-prevention flag (suppresses the design
 *                                  auto-save subscriber during a passive re-pull)
 *
 * @returns {{ recoverAfterRestart: (health: object) => Promise<void> }}
 */
export function initConnectionMonitor({
  api,
  store,
  assemblyRenderer,
  setSyncStatus,
  syncLog,
  setReloadingFromSSE,
}) {
  let _restartHandling = false

  async function recoverAfterRestart(health) {
    // The backend's per-session revision resets low after a restart; clear the
    // stale-response watermark so the re-pulled design isn't dropped as "older".
    api.resetRevisionWatermark?.()
    const assemblyMode = store.getState().assemblyActive
    if (assemblyMode) {
      // Assemblies are recovered server-side (session-cache). Re-pull + rebuild.
      await api.getAssembly()
      const asm = store.getState().currentAssembly
      if (asm) {
        ;(asm.instances ?? []).forEach(i => assemblyRenderer.invalidateInstance(i.id))
        await assemblyRenderer.rebuild(asm)
        await assemblyRenderer.rebuildLinkers(asm)
      }
      return
    }
    if (health?.design_loaded) {
      // Server-side recovery worked — passively re-pull design + geometry.
      setReloadingFromSSE(true)
      try { await api.getDesign(); await api.getGeometry() }
      finally { setReloadingFromSSE(false) }
      return
    }
    // Backend came back with no design. Offer to restore from this tab's cache.
    const cached = api.getPersistedDesign()
    if (cached && window.confirm(
        'The backend restarted and no longer has your design loaded.\n\n' +
        'Restore your work from this browser tab?')) {
      await api.importDesign(JSON.stringify(cached))
      await api.getGeometry()
    }
  }

  connectionMonitor.start({ onChange: async (evt) => {
    if (evt.type === 'disconnected') {
      setSyncStatus('red', 'reconnecting…')
      syncLog('warn', 'CONN', 'backend unreachable — reconnecting')
    } else if (evt.type === 'reconnected') {
      setSyncStatus('green', 'reconnected')
      syncLog('info', 'CONN', 'backend reachable again')
    } else if (evt.type === 'restarted') {
      syncLog('warn', 'CONN', 'backend restarted (new instance) — re-syncing')
      setSyncStatus('yellow', 'backend restarted — re-syncing…')
      if (_restartHandling) return
      _restartHandling = true
      try {
        await recoverAfterRestart(evt.health)
        setSyncStatus('green', 'synced')
      } catch (err) {
        setSyncStatus('red', 'recovery error')
        syncLog('err', 'CONN', `recovery failed: ${err?.message ?? err}`)
      } finally {
        _restartHandling = false
      }
    }
  } })

  return { recoverAfterRestart }
}

// While a sibling tab is live-editing this doc, an incoming file-changed for our
// open design is a self/sibling autosave echo, NOT an external edit — so we must
// NOT reload it into the backend (that reloads a STALE autosave snapshot and
// clobbers the in-progress edits). design-changed reliably precedes the autosave's
// SSE (both serialize on the editor's main thread, broadcast first), so this window
// is robust even when a heavy 2D re-render delays the file-saved broadcast.
const _RELOAD_SUPPRESS_MS = 10000

/**
 * Auto-save (debounced write-back to workspace files) + the Library-SSE handler.
 *
 * This module OWNS the four loop-prevention flags shared across the persistence
 * paths (the connection monitor, the cross-tab broadcast handler, the explicit
 * save dispatch and the part-save fast path all touch them):
 *   _savingAssembly        — set while an assembly autosave is in-flight so its own
 *                            store update doesn't re-trigger the subscriber
 *   _reloadingFromSSE      — set while reloading a design from an SSE / broadcast so
 *                            the resulting store update doesn't re-trigger auto-save
 *   _selfSavedPaths        — paths saved by THIS tab; SSE echoes for these are skipped.
 *                            EXPOSED BY REFERENCE so the distant add/delete sites
 *                            (save dispatch, part-save fast path, broadcast file-saved)
 *                            mutate the same Set this module reads.
 *   _lastSameDocActivityMs — timestamp of the last sibling-tab design-changed for OUR
 *                            doc; suppresses a following file-changed reload.
 *
 * Both autosave subscribers and the SSE handler register on construction, so the
 * factory call must sit at the original design-subscriber registration point to
 * preserve store-subscription order. `getAssemblyRefresh` is lazy because the
 * coalesced part-refresh is wired a little later in main().
 *
 * Deps:
 *   store, api                 — store slices + backend
 *   fileIo                     — ui/file_io.js (savePartToAssembly)
 *   syncBadge                  — ui/sync_badge.js (setSyncStatus / syncLog)
 *   libraryPanel               — welcome-screen file list (refresh)
 *   getAssemblyRefresh         — lazy () => the coalesced assembly part-refresh
 *   getPartEditContext         — lazy () => main.js's _partEditContext (mutable)
 *   getWorkspacePath           — lazy () => the open design's workspace path (mutable)
 *   getAssemblyWorkspacePath   — lazy () => the open assembly's workspace path (mutable)
 *   setAssemblyWorkspacePath   — writes main.js's _assemblyWorkspacePath
 *
 * @returns {{
 *   selfSavedPaths: Set<string>,
 *   setReloadingFromSSE: (v: boolean) => void,
 *   getReloadingFromSSE: () => boolean,
 *   getSavingAssembly: () => boolean,
 *   markSameDocActivity: () => void,
 *   handleLibraryEvent: (evt: object) => void,
 * }}
 */
export function initAutosaveSync({
  store,
  api,
  fileIo,
  syncBadge,
  libraryPanel,
  getAssemblyRefresh,
  getPartEditContext,
  getWorkspacePath,
  getAssemblyWorkspacePath,
  setAssemblyWorkspacePath,
}) {
  let _savingAssembly   = false
  let _reloadingFromSSE = false
  const _selfSavedPaths = new Set()
  let _lastSameDocActivityMs = 0
  let _designSaveTimer  = null
  let _assemblySaveTimer = null
  let _partSaveTimer = null
  let _libRefreshTimer = null

  store.subscribeSlice('design', (newState, prevState) => {
    // Skip non-persistent syncs: transient deform previews AND protected simulation
    // loadout selections. The latter must remain selected for viewing; attempting to
    // autosave a protected branch invokes the 409 recovery path, which activates the
    // editable branch and silently undoes the warning-icon rollback.
    if (newState.currentDesign !== prevState.currentDesign && api.wasLastDesignSyncTransient()) return
    if (getPartEditContext()) {
      if (newState.currentDesign === prevState.currentDesign) return
      syncBadge.setSyncStatus('yellow', 'auto-saving…')
      clearTimeout(_partSaveTimer)
      _partSaveTimer = setTimeout(() => {
        fileIo.savePartToAssembly({ silent: true })
      }, 900)
      return
    }
    if (!getWorkspacePath() || _reloadingFromSSE) return
    if (newState.currentDesign === prevState.currentDesign) return
    syncBadge.setSyncStatus('yellow', 'saving…')
    clearTimeout(_designSaveTimer)
    _designSaveTimer = setTimeout(async () => {
      const path = getWorkspacePath()
      if (!path) return
      syncBadge.syncLog('info', 'SAVE', `design → ${path}`)
      _selfSavedPaths.add(path)
      nadocBroadcast.emit('file-saved', { path })   // tell sibling tabs to skip the SSE reload echo
      try {
        await api.saveDesignToWorkspace(path)
        syncBadge.setSyncStatus('green', 'saved')
        setTimeout(() => _selfSavedPaths.delete(path), 5000)
      } catch (err) {
        syncBadge.setSyncStatus('red', 'save error')
        syncBadge.syncLog('err', 'SAVE', `failed: ${err?.message ?? err}`)
        setTimeout(() => _selfSavedPaths.delete(path), 5000)
      }
    }, 1500)
  })

  store.subscribeSlice('assembly', (newState, prevState) => {
    const assemblyWorkspacePath = getAssemblyWorkspacePath()
    if (!assemblyWorkspacePath || _savingAssembly) return
    if (newState.currentAssembly === prevState.currentAssembly) return
    syncBadge.setSyncStatus('yellow', 'saving…')
    clearTimeout(_assemblySaveTimer)
    _assemblySaveTimer = setTimeout(async () => {
      const path = getAssemblyWorkspacePath()
      if (!path || _savingAssembly) return
      _savingAssembly = true
      // Mark the assembly file self-saved so its own watchdog `file-changed` echo
      // (which fires after every part-edit-driven re-resolve) is skipped in
      // `handleLibraryEvent` instead of triggering a library refresh.
      const _savedPaths = new Set([path])
      _selfSavedPaths.add(path)
      try {
        const r = await api.saveAssemblyAs(path)
        if (r?.path) { setAssemblyWorkspacePath(r.path); _selfSavedPaths.add(r.path); _savedPaths.add(r.path) }
        syncBadge.syncLog('info', 'SAVE', `assembly → ${r?.path}`)
        syncBadge.setSyncStatus('green', 'saved')
      } catch (err) {
        syncBadge.setSyncStatus('red', 'save error')
        syncBadge.syncLog('err', 'SAVE', `assembly failed: ${err?.message ?? err}`)
      } finally {
        _savingAssembly = false
        setTimeout(() => { for (const p of _savedPaths) _selfSavedPaths.delete(p) }, 5000)
      }
    }, 1500)
  })

  function _scheduleLibraryRefresh() {
    clearTimeout(_libRefreshTimer)
    _libRefreshTimer = setTimeout(() => libraryPanel.refresh(), 400)
  }

  // A sibling tab broadcast `file-saved` for a path. Suppress the resulting SSE
  // file-changed echo ONLY when the sibling shares OUR backend document: a
  // same-doc sibling's autosave is a stale snapshot we already sync via the
  // doc-scoped design-changed broadcast, so reloading it would clobber live
  // edits. A DIFFERENT-doc sibling editing the same workspace file is a GENUINE
  // external change — its edits do NOT ride our design-changed (isSameDoc=false),
  // so the SSE file-changed is the only sync channel and must NOT be suppressed.
  // (ISSUE-2: doc-agnostic suppression here swallowed cross-tab edits for minutes.)
  function registerSiblingSave(path, sameDoc) {
    if (!path || !sameDoc) return
    _selfSavedPaths.add(path)
    setTimeout(() => _selfSavedPaths.delete(path), 5000)
  }

  function handleLibraryEvent({ type, path, file_type }) {
    if (type !== 'file-changed' && type !== 'file-deleted') return
    syncBadge.syncLog('info', 'SSE', `${type} ${file_type}:${path}`)

    // Skip reacting to files we just saved ourselves (SSE echo). Do this BEFORE
    // the library refresh: a self-save doesn't change the file LIST, and a part
    // edit fires several self-save echoes (part file ×2 + the assembly autosave),
    // each of which used to run a fresh GET /library/files — a flood that piled
    // up to multi-second responses.
    if (type === 'file-changed' && _selfSavedPaths.has(path)) {
      syncBadge.syncLog('info', 'SSE', `skipped (self-saved echo)`)
      return
    }
    // A genuine external change → refresh the file list, debounced so a burst of
    // distinct events collapses to one GET /library/files.
    _scheduleLibraryRefresh()

    if (file_type === 'part' && store.getState().assemblyActive) {
      // Assembly tab: a part file changed (external edit, or — if the broadcast
      // didn't beat the SSE — our own part-editor save). Route through the
      // COALESCED refresh so this + the `part-design-updated` broadcast + any
      // burst of saves collapse into ONE getAssembly + rebuild + getInstanceDesign
      // instead of a per-instance, per-event flood. The coalesced refresh
      // invalidates every instance sharing this source and fetches the design once.
      const assembly = store.getState().currentAssembly
      const affected = (assembly?.instances ?? []).filter(
        i => i.source?.type === 'file' && i.source.path === path,
      )
      if (affected.length) {
        syncBadge.syncLog('info', 'SSE', `${affected.length} instance(s) affected → coalesced refresh`)
        getAssemblyRefresh().requestRefresh(affected[0].id, 'sse')
      }
    } else if (file_type === 'part' && !store.getState().assemblyActive && getWorkspacePath() === path) {
      // Design tab: this is the file we have open. If a sibling tab is live-editing
      // the SAME backend document (recent design-changed), this file-changed is a
      // self/sibling autosave echo — reloading it would push a STALE snapshot into
      // the backend and clobber the in-progress edits. Same-doc sync already
      // happens via the design-changed broadcast, so skip the reload.
      if (Date.now() - _lastSameDocActivityMs < _RELOAD_SUPPRESS_MS) {
        syncBadge.syncLog('info', 'SSE', `skipped reload of ${path} (live same-doc editing)`)
        return
      }
      // Otherwise treat as a genuine external edit and reload.
      syncBadge.syncLog('info', 'SSE', `reloading design from ${path}`)
      syncBadge.setSyncStatus('yellow', 'syncing…')
      _reloadingFromSSE = true
      api.getLibraryFileContent(path)
        .then(result => result?.content ? api.importDesign(result.content) : null)
        .then(() => { syncBadge.setSyncStatus('green', 'synced') })
        .catch(err => { syncBadge.setSyncStatus('red', 'sync error'); syncBadge.syncLog('err', 'SSE', `reload failed: ${err?.message ?? err}`) })
        .finally(() => { _reloadingFromSSE = false })
    }
  }
  api.subscribeLibraryEvents(handleLibraryEvent)

  return {
    selfSavedPaths: _selfSavedPaths,
    setReloadingFromSSE: (v) => { _reloadingFromSSE = v },
    getReloadingFromSSE: () => _reloadingFromSSE,
    getSavingAssembly: () => _savingAssembly,
    markSameDocActivity: () => { _lastSameDocActivityMs = Date.now() },
    registerSiblingSave,
    handleLibraryEvent,
  }
}
