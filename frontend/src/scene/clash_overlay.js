// clash_overlay.js — design-layer steric-clash highlight (the "clash" view tool).
//
// Fetches the backend clash report (GET /design/clashes, over the POSED geometry
// with cluster folds + deformations applied), paints the clashing backbone beads
// with a red glow, and shows a small count badge. Re-fetches whenever the design
// geometry changes while the toggle is on.
//
// Display-layer only — never touches topology. Modelled on the "undefined bases"
// highlight path (undefined_highlight.js) and on anchor_glow.js for the
// rebuild-reapply subscription. Factory:
//   initClashOverlay({ store, designRenderer, api }) → { toggle, refresh, clear, isOn }

import { getClashes } from '../api/client.js'

/**
 * PURE: given the clash report's pair list + the renderer's backbone entries,
 * return the subset of entries that sit on a clashing nucleotide.
 *
 * Each clash pair carries two sides { helix_id, bp_index, direction }; a backbone
 * entry is highlighted when its nucleotide matches either side of any pair.
 *
 * @param {Array<{a:object, b:object}>} clashes  report.clashes
 * @param {Array} backboneEntries  designRenderer.getBackboneEntries()
 * @returns {Array} de-duplicated entries to highlight (possibly empty)
 */
export function clashEntriesFor(clashes, backboneEntries) {
  if (!clashes?.length || !backboneEntries?.length) return []
  const keys = new Set()
  for (const c of clashes ?? []) {
    for (const side of [c?.a, c?.b]) {
      if (side) keys.add(`${side.helix_id}:${side.bp_index}:${side.direction}`)
    }
  }
  const seen = new Set()
  const out = []
  for (const e of backboneEntries) {
    const n = e?.nuc
    if (!n) continue
    if (keys.has(`${n.helix_id}:${n.bp_index}:${n.direction}`) && !seen.has(e)) {
      seen.add(e)
      out.push(e)
    }
  }
  return out
}

export function initClashOverlay({ store, designRenderer, api = { getClashes } } = {}) {
  let _on = false
  let _lastGeometry = null
  let _lastClashes = null   // last report's pair list, for repaint-without-refetch
  const _legend     = document.getElementById('clash-legend')
  const _legendText = document.getElementById('clash-legend-text')

  function _setLegend(count) {
    if (!_legend) return
    _legend.classList.add('visible')
    _legend.classList.toggle('none', count === 0)
    if (_legendText) _legendText.textContent = count === 1 ? '1 clash' : `${count} clashes`
  }

  function clear() {
    _lastClashes = null
    designRenderer?.clearClashHighlight?.()
    _legend?.classList.remove('visible')
  }

  /** Re-resolve the LAST report against the current backbone entries — no refetch.
   *  For a rebuild that did not move anything (the capture-strand injection), the
   *  report is still valid; only the entry objects it was painted onto are stale. */
  function _repaint() {
    if (!_on || !_lastClashes) return
    const entries = clashEntriesFor(_lastClashes, designRenderer?.getBackboneEntries?.() || [])
    if (entries.length) designRenderer?.setClashHighlight?.(entries)
    else designRenderer?.clearClashHighlight?.()
  }

  /** Re-fetch the clash report and repaint (no-op while toggled off). */
  async function refresh() {
    if (!_on) return
    const design = store?.getState?.().currentDesign
    if (!design) { clear(); return }
    const report = await (api?.getClashes ?? getClashes)()
    if (!_on) return   // toggled off during the await
    const clashes = report?.clashes ?? []
    _lastClashes = clashes
    const entries = clashEntriesFor(clashes, designRenderer?.getBackboneEntries?.() || [])
    if (entries.length) designRenderer?.setClashHighlight?.(entries)
    else designRenderer?.clearClashHighlight?.()
    _setLegend(report?.count ?? 0)
  }

  /** Flip the toggle; returns the new on/off state. */
  function toggle() {
    _on = !_on
    if (_on) { _lastGeometry = store?.getState?.().currentGeometry; refresh() }
    else clear()
    return _on
  }

  function isOn() { return _on }

  // A geometry rebuild replaces the backbone entries (and clears the glow layer)
  // and, more importantly, changes the posed positions the clash report is about —
  // re-fetch. Registered after the designRenderer subscriber so getBackboneEntries()
  // is fresh by the time the (async) report returns.
  store?.subscribe?.(() => {
    const geo = store.getState().currentGeometry
    if (_on && geo !== _lastGeometry) { _lastGeometry = geo; refresh() }
  })

  // A DISPLAY-ONLY rebuild (the oxDNA capture-strand injection) replaces the backbone
  // entries without touching the store or moving a single design nucleotide. Repaint
  // the standing report rather than re-fetching one per keystroke.
  window.addEventListener('nadoc:display-rebuilt', () => _repaint())

  return { toggle, refresh, clear, isOn }
}
