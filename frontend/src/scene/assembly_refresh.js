// Coalesced assembly part-refresh.
//
// A single part edit fires BOTH a `part-design-updated` broadcast AND a watchdog
// `file-changed` SSE; a slider drag in the part editor fires a whole BURST of
// them. Each used to run a full part-instance refresh (getAssembly +
// rebuild-all-instances + getInstanceDesign) — so N rapid edits → N concurrent
// heavy rebuilds that saturated the backend (20-30 s responses) AND raced into
// the hull+cylinder LOD overlay. This factory funnels every trigger through a
// debounced, drop-while-in-flight scheduler so a burst collapses to ONE refresh.
//
// Extracted from main.js (Tier-3 "Coalesced assembly part-refresh" region).
// Three-Layer Law: this re-fetches geometry/transforms for the assembly display
// after a part edit auto-resolved on the backend — it never writes topology.

// Factory. Deps:
//   store                  — { getState } (reads assemblyActive / currentAssembly)
//   api                    — { getAssembly, getInstanceDesign }
//   assemblyRenderer       — { rebuild, rebuildLinkers }
//   assemblyJointRenderer  — { rebuild }
//   syncLog(level,tag,msg) — sync console logger
//   setSyncStatus(state,label) — sync-status badge setter
//   syncAssemblyBluntEnds()    — re-derive assembly blunt-end caps
//   selfSavedPaths         — Set of paths saved by THIS tab (mutated by reference)
//   getClusterPanel        — () => clusterPanel (lazy — wired after this init)
// Returns { requestRefresh, flush, dispose }.
export function initAssemblyRefresh({
  store,
  api,
  assemblyRenderer,
  assemblyJointRenderer,
  syncLog,
  setSyncStatus,
  syncAssemblyBluntEnds,
  selfSavedPaths,
  getClusterPanel,
}) {
  let _timer    = null
  let _inFlight = false
  let _pending  = false
  let _id       = null
  let _reason   = 'part update'

  // Public entry: schedule a coalesced refresh for `instanceId`. A burst within
  // the debounce window collapses to one run; a trigger arriving mid-flight
  // queues exactly one follow-up.
  function requestRefresh(instanceId, reason = 'part update') {
    if (!instanceId || !store.getState().assemblyActive) return
    _id = instanceId
    _reason = reason
    if (_inFlight) { _pending = true; return }
    clearTimeout(_timer)
    _timer = setTimeout(_run, 250)
  }

  async function _run() {
    if (_inFlight) { _pending = true; return }
    _inFlight = true
    _pending  = false
    try {
      await _refreshAssemblyPartInstance(_id, _reason)
    } catch (err) {
      console.warn('[sync] assembly part refresh failed:', err?.message ?? err)
    } finally {
      _inFlight = false
      // A trigger arrived while we were refreshing — run exactly once more.
      if (_pending) {
        _pending = false
        clearTimeout(_timer)
        _timer = setTimeout(_run, 250)
      }
    }
  }

  async function _refreshAssemblyPartInstance(instanceId, reason = 'part update') {
    if (!instanceId || !store.getState().assemblyActive) return
    syncLog('info', 'ASM', `${reason}: refreshing ${instanceId}`)
    setSyncStatus('yellow', 'syncing part…')

    // The edited part is usually shared by several instances (a polymerized
    // chain). Do NOT invalidate per-instance: on the shared renderer
    // `invalidateInstance` IGNORES the id and triggers a FULL rebuild, so a
    // per-instance loop fired one rebuild PER copy (40 instances → 40
    // getAssemblyGeometry calls → backend saturation + the rebuild-race overlay).
    // A single `rebuild()` below disposes every source and refetches the batch
    // geometry once, so all copies pick up the new shape from one rebuild.
    const cur     = store.getState().currentAssembly
    const srcInst = cur?.instances?.find(i => i.id === instanceId)
    const srcPath = srcInst?.source?.type === 'file' ? srcInst.source.path : null
    const affected = srcPath
      ? (cur?.instances ?? []).filter(i => i.source?.type === 'file' && i.source.path === srcPath)
      : (srcInst ? [srcInst] : [])

    // The part-editor save also writes the .nadoc file, which fires a watchdog
    // SSE `file-changed`. Mark the path self-saved so `_handleLibraryEvent`
    // doesn't schedule a second (coalesced-but-still-extra) refresh for it.
    if (srcPath) {
      selfSavedPaths.add(srcPath)
      setTimeout(() => selfSavedPaths.delete(srcPath), 5000)
    }

    // getAssembly pulls the re-docked transforms the backend produced when the
    // part edit auto-resolved (PATCH /assembly/instances/{id}/design). rebuild()
    // then disposes all sources and refetches fresh geometry once (the part-edit
    // cleared the backend geo cache), so every instance updates.
    //
    // CRITICAL: use the EXPANDED store assembly, NOT result.assembly. getAssembly()
    // returns the RAW backend JSON, whose `assembly` is the v2 wire format —
    // parts live under `instances_v2` and the v1 `instances` field is dropped
    // (_assembly_response does `full.pop("instances")`). So result.assembly.instances
    // is undefined → rebuild() sees zero instances and DISPOSES every source,
    // blanking the assembly (visible only after a rep-change forced a fresh
    // rebuild from the store). _syncFromAssemblyResponse already expanded v2 → v1
    // into store.currentAssembly (`.instances` populated), so read that.
    await api.getAssembly()
    const assembly = store.getState().currentAssembly
    if (!assembly?.instances?.length) return
    await assemblyRenderer.rebuild(assembly)
    assemblyRenderer.rebuildLinkers(assembly)
    syncAssemblyBluntEnds()
    assemblyJointRenderer.rebuild(assembly)
    try {
      // All affected instances share one source design — fetch it ONCE.
      const r = await api.getInstanceDesign(instanceId)
      if (r?.design) {
        const clusterPanel = getClusterPanel?.()
        for (const i of affected) clusterPanel?.syncInstanceDesign(i.id, r.design)
      }
    } catch { /* sidebar cache refresh is best-effort */ }
    setSyncStatus('green', 'part synced')
  }

  // Cancel the pending debounce and run the coalesced refresh immediately (used
  // when the caller knows it wants the freshest geometry now, not after 250 ms).
  function flush() {
    clearTimeout(_timer)
    _timer = null
    return _run()
  }

  // Tear down: cancel any pending timer and reset state.
  function dispose() {
    clearTimeout(_timer)
    _timer = null
    _inFlight = false
    _pending = false
    _id = null
  }

  return { requestRefresh, flush, dispose }
}
