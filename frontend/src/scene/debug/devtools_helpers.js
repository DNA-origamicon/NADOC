// ── Browser dev-tools debug helpers ─────────────────────────────────────────
//
//  window._nadocDebug.help()           — print this usage guide
//  window._nadocDebug.posTrace(on)     — log every backbone-bead position update
//                                        with a stack trace (cadnano-active only)
//  window._nadocDebug.snapPos(label)   — snapshot all bead [x,y,z] positions now
//  window._nadocDebug.diffPos(a, b)    — compare two snapshots; print moved beads
//  window._nadocDebug.storeTrace(keys) — log every store.setState() that touches
//                                        the listed keys (or all keys if omitted)
//  window._nadocDebug.subTrace(on)     — log every store subscriber notification
//                                        when cadnano is active
//  window._cnDebug = true              — cadnano_view verbose logging (existing)
//  window._cnCheck()                   — snapshot cadnano state (existing)
//  window._cnMonitor()                 — watch bead-0.x for drift (existing)
//
// Lifted verbatim from the main() closure (the closure-captured deps became
// factory params). `window._nadocDebug` is a shared debug namespace: photo-mode
// attaches extra methods (`.photoMaterials` etc.) onto the returned object after
// creation, and three Playwright e2e specs drive `.snapPos` / `.refetch` /
// `.overhangLinkArcs` — those are the real gate for this module.

/**
 * Build the `window._nadocDebug` console-debug namespace.
 * @param {object} deps
 * @param {object} deps.designRenderer
 * @param {object} deps.store
 * @param {object} deps.api
 * @param {object} deps.overhangLinkArcs
 * @param {object} deps.selectionManager
 * @param {object} deps.scene
 * @returns {object} the debug API (also carries test-only module handles)
 */
export function initDevtoolsDebug({ designRenderer, store, api, overhangLinkArcs, selectionManager, scene }) {
  let _posTraceOn = false
  let _storeTraceUnsub = null
  const _savedDrFns = {}  // saves originals when posTrace is on

  /** Intercept designRenderer position-setting functions and log with stack. */
  function posTrace(on = true) {
    if (on === _posTraceOn) return
    _posTraceOn = on
    const fns = ['applyUnfoldOffsets', 'applyDeformLerp', 'applyCadnanoPositions']

    if (on) {
      for (const name of fns) {
        const original = designRenderer[name].bind(designRenderer)
        _savedDrFns[name] = original
        designRenderer[name] = function(...args) {
          if (store.getState().cadnanoActive)
            console.trace(`[posTrace f${window._cnFrame ?? '?'}] designRenderer.${name}()`)
          return original(...args)
        }
      }
      console.log('[nadocDebug.posTrace] ON — stack traces logged when cadnano active')
    } else {
      for (const name of fns) {
        if (_savedDrFns[name]) { designRenderer[name] = _savedDrFns[name]; delete _savedDrFns[name] }
      }
      console.log('[nadocDebug.posTrace] OFF')
    }
  }

  /** Return a Map<key, [x,y,z]> snapshot of all non-phantom backbone bead positions. */
  function snapPos(label = 'snap') {
    const m = new Map()
    for (const e of designRenderer.getBackboneEntries()) {
      if (e.nuc.helix_id?.startsWith('__')) continue
      m.set(`${e.nuc.helix_id}:${e.nuc.bp_index}:${e.nuc.direction}`, [e.pos.x, e.pos.y, e.pos.z])
    }
    console.log(`[nadocDebug.snapPos] "${label}" — ${m.size} beads, cadnanoActive=${store.getState().cadnanoActive}`)
    return { label, map: m }
  }

  /** Print beads that moved more than threshold nm between two snapshots. */
  function diffPos(a, b, threshold = 0.05) {
    const moved = []
    for (const [key, [ax, ay, az]] of a.map) {
      const p = b.map.get(key)
      if (!p) { moved.push([key, 'missing in B']); continue }
      const [bx, by, bz] = p
      const d = Math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)
      if (d > threshold)
        moved.push([key, `Δ=${d.toFixed(3)} nm`, `(${ax.toFixed(2)},${ay.toFixed(2)},${az.toFixed(2)})→(${bx.toFixed(2)},${by.toFixed(2)},${bz.toFixed(2)})`])
    }
    console.group(`[nadocDebug.diffPos] "${a.label}"→"${b.label}": ${moved.length} beads moved`)
    moved.slice(0, 25).forEach(r => console.log(...r))
    if (moved.length > 25) console.log(`  …and ${moved.length - 25} more`)
    console.groupEnd()
    return moved
  }

  /**
   * Log store.setState() calls that touch the listed keys (pass [] for ALL).
   * Returns an unsubscribe function to stop tracing.
   */
  function storeTrace(keys = []) {
    if (_storeTraceUnsub) { _storeTraceUnsub(); _storeTraceUnsub = null }
    const orig = store.setState.bind(store)
    store.setState = function(partial) {
      const changed = Object.keys(partial)
      const relevant = keys.length ? changed.filter(k => keys.includes(k)) : changed
      if (relevant.length > 0)
        console.trace(`[storeTrace f${window._cnFrame ?? '?'}] setState: ${relevant.join(', ')}`)
      return orig(partial)
    }
    const stop = () => { store.setState = orig; _storeTraceUnsub = null; console.log('[nadocDebug.storeTrace] OFF') }
    _storeTraceUnsub = stop
    console.log(`[nadocDebug.storeTrace] ON — watching: ${keys.length ? keys.join(', ') : 'ALL keys'}`)
    return stop
  }

  /**
   * Wrap every store subscriber to log which one is firing (by insertion index)
   * and whether cadnano is active.  Heavy — only use when debugging subscriber order.
   */
  function subTrace(on = true) {
    window._cnSubTrace = on
    console.log(`[nadocDebug.subTrace] ${on ? 'ON' : 'OFF'} — set window._cnSubTrace=false to stop`)
    // Actual interception is done by patching store.subscribe retroactively; since
    // that's not feasible post-init, use this flag to gate logging inside the
    // cadnano reapply subscriber (which is the most critical one).
  }

  /** Inventory ds-linker state: backend (currentDesign) vs frontend (renderer)
   *  ‒ surfaces mismatches like "0 connections but bridge meshes still in scene".
   *  Returns the inventory object so you can grep into specifics in the console. */
  function linkers() {
    const state = store.getState()
    const design = state.currentDesign
    const geometry = state.currentGeometry ?? []
    if (!design) {
      console.warn('[linkers] no currentDesign')
      return null
    }
    const conns = design.overhang_connections ?? []
    const lnkHelices = (design.helices ?? []).filter(h => h.id?.startsWith('__lnk__'))
    const lnkStrands = (design.strands ?? []).filter(s => s.id?.startsWith('__lnk__'))
    const lnkNucs    = geometry.filter(n => (n.helix_id ?? '').startsWith('__lnk__'))
    const helixCtrl  = designRenderer.getHelixCtrl?.()
    const allEntries = helixCtrl?.getBackboneEntries?.() ?? []
    const lnkEntries = allEntries.filter(e => (e.nuc.helix_id ?? '').startsWith('__lnk__'))
    const arcChildren = overhangLinkArcs?.group?.children ?? []

    console.group(`[NADOC linker inventory] connections=${conns.length}`)
    if (conns.length) {
      console.group(`overhang_connections (${conns.length})`)
      for (const c of conns) console.log(
        `${c.id} "${c.name}" type=${c.linker_type} ` +
        `A=${c.overhang_a_id}/${c.overhang_a_attach} ` +
        `B=${c.overhang_b_id}/${c.overhang_b_attach} ` +
        `len=${c.length_value} ${c.length_unit}`)
      console.groupEnd()
    }
    console.log(`__lnk__ helices in design.helices: ${lnkHelices.length}`,
      lnkHelices.map(h => h.id))
    console.log(`__lnk__ strands in design.strands: ${lnkStrands.length}`,
      lnkStrands.map(s => s.id))
    console.log(`__lnk__ nucs in currentGeometry:   ${lnkNucs.length}`)
    console.log(`__lnk__ entries in renderer:       ${lnkEntries.length}`)
    console.log(`overhangLinkArcs group children:   ${arcChildren.length}`,
      arcChildren.map(c => c.name || `(${c.type})`))
    console.groupEnd()

    const issues = []
    if (conns.length === 0) {
      if (lnkHelices.length)  issues.push(`${lnkHelices.length} __lnk__ helices but 0 connections`)
      if (lnkStrands.length)  issues.push(`${lnkStrands.length} __lnk__ strands but 0 connections`)
      if (lnkNucs.length)     issues.push(`${lnkNucs.length} __lnk__ nucs in geometry but 0 connections`)
      if (lnkEntries.length)  issues.push(`${lnkEntries.length} __lnk__ entries in renderer but 0 connections`)
      if (arcChildren.length) issues.push(`${arcChildren.length} overhangLinkArcs children but 0 connections`)
    }
    const expectedHelixIds = new Set(conns.map(c => `__lnk__${c.id}`))
    for (const h of lnkHelices) {
      if (!expectedHelixIds.has(h.id)) issues.push(`orphan __lnk__ helix in design: ${h.id}`)
    }
    const renderedHelixIds = new Set(lnkEntries.map(e => e.nuc.helix_id))
    for (const hid of renderedHelixIds) {
      if (!expectedHelixIds.has(hid)) issues.push(`renderer has __lnk__ entries for orphan helix: ${hid}`)
    }
    if (issues.length) {
      console.warn('[linkers] mismatches detected:')
      for (const i of issues) console.warn('  • ' + i)
    } else {
      console.log('[linkers] ✓ no mismatches')
    }
    return { conns, lnkHelices, lnkStrands, lnkNucs, lnkEntries, arcChildren, issues }
  }

  /** Force a full design_renderer rebuild by replacing currentGeometry's
   *  array reference. Useful to confirm whether a stale visual is the
   *  positions_only/cluster_only path failing to clean up something the
   *  full rebuild does correctly. */
  function forceRebuild() {
    const state = store.getState()
    if (!state.currentGeometry) {
      console.warn('[forceRebuild] no currentGeometry to refresh')
      return
    }
    // New array reference triggers design_renderer's geoChanged path,
    // bypassing the visual-only-design-change early-return.
    store.setState({
      currentGeometry:  [...state.currentGeometry],
      currentHelixAxes: state.currentHelixAxes
        ? { ...state.currentHelixAxes }
        : state.currentHelixAxes,
    })
    console.log('[forceRebuild] dispatched — design_renderer should rebuild now')
  }

  /** Trigger a clean backend re-fetch of design + geometry, replacing all
   *  stores. The ground truth for "what should be rendered". If linker
   *  meshes vanish after this, the bug is in the seek/undo/redo update
   *  path leaving stale meshes; if they persist, the bug is in the backend
   *  state itself. */
  async function refetch() {
    console.log('[refetch] re-fetching design + geometry from backend…')
    await api.getDesign()
    await api.getGeometry()
    console.log('[refetch] done — compare with .linkers() output')
  }

  function help() {
    console.log(`
NADOC debug tools — window._nadocDebug
  .posTrace(true/false)   Intercept designRenderer position setters; log stack traces when cadnano is active.
                          Reveals exactly which fn last moved beads.  Use with .snapPos / .diffPos for before/after.
  .snapPos("label")       → {label, map}  Snapshot all backbone bead [x,y,z] positions.
  .diffPos(a, b)          Compare two snapshots; shows beads that moved > 0.05 nm.
  .storeTrace(["key"…])   Patch store.setState to log matching keys with stack traces.
                          Pass [] for all keys.  Returns unsubscribe fn.
  .subTrace(true)         Set window._cnSubTrace=true to gate extra logging in key subscribers.

  .linkers()              Print backend vs renderer ds-linker inventory; flags mismatches like
                          "0 connections but bridge meshes still in scene". Returns the inventory.
  .forceRebuild()         Bump currentGeometry's array ref so design_renderer rebuilds the scene.
                          Useful to test whether a stale visual is the seek/cluster path leaving
                          something behind that a full rebuild would clear.
  .refetch()              await getDesign() + getGeometry() — restores the canonical backend state.
                          Use as ground truth: if linker meshes vanish here but reappear after a
                          seek, the bug is in the seek path; if they persist here, the bug is on
                          the backend.

Also available (cadnano_view.js):
  window._cnDebug = true  Verbose per-frame cadnano logging.
  window._cnCheck()       Show cadnano state: active, midX, bead counts at midX vs off-midX.
  window._cnMonitor()     Watch bead-0.x every frame for drift.
  window._cnEntries()     Return all backbone entries for manual inspection.

Typical debugging workflow for "reverts to 3D" bug:
  1.  _nadocDebug.posTrace(true)              // start intercepting
  2.  Delete a crossover in cadnano mode
  3.  Check console — last logged stack trace before positions go wrong is the culprit
  4.  OR: snap1=_nadocDebug.snapPos('before'); delete crossover; snap2=_nadocDebug.snapPos('after')
         _nadocDebug.diffPos(snap1, snap2)    // see which beads moved and how far
`)
  }

  return {
    posTrace, snapPos, diffPos, storeTrace, subTrace, linkers, forceRebuild, refetch, help,
    // Test-only handles — expose the running module instances so Playwright
    // can drive selection / inspect arc meshes without simulating mouse
    // events on the 3D canvas.
    selectionManager, overhangLinkArcs, scene,
  }
}
