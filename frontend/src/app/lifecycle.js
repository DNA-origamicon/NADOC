import * as connectionMonitor from '../shared/connection_monitor.js'

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
