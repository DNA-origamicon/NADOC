// Selection-level model (ISSUE-4 Phase 2 "drill v2").
//
// Collapses the three overlapping legacy mechanisms — auto-drill ladder, manual
// filter pins, and the Tab drill-lock — into ONE concept: an active
// `selectionLevel`. There is exactly one engaged level at a time, so the old
// "red border means two different things" ambiguity disappears.
//
//   default → no button engaged. 1st click selects the STRAND; 2nd click on the
//             selected strand selects the leaf UNDER THE CURSOR (bead → end |
//             cone/arc → xover); a repeat click KEEPS it. Drill ladder.
//   strand → every click selects the whole clicked strand (no leaf drill).
//   cluster | domain | end | xover → every click selects at that FIXED level.
//
// Tab cycles cluster → strand → domain → end → xover → none(default) → cluster.
// Escape returns to `default`. The #select-filter level buttons drive the SAME
// state (clust/strand/line/ends/xover); no button lit = `default`.
//
// Drill-v2 is now the DEFAULT (flipped 2026-06-06); opt out via
// `localStorage NADOC_DRILL_V2='false'` or `?drillv2=0`. The legacy auto-drill/
// pin/lock paths still exist behind the opt-out but are dead by default (their
// physical deletion is a deferred cleanup pass).
//
// Everything here is pure (no DOM / scene / store) so it unit-tests directly.

export const LEVELS    = ['default', 'cluster', 'strand', 'domain', 'end', 'xover']
// Tab cycles cluster → strand → domain → end → xover → none(default) → cluster.
// `default` = no button engaged = the drill ladder (user model 2026-06-06).
export const TAB_CYCLE = ['cluster', 'strand', 'domain', 'end', 'xover', 'default']

// Filter-button dataKey ↔ selectionLevel. `strand` is now a DISTINCT fixed level
// (every click → whole strand), separate from `default` (no button = drill ladder).
// `default` has NO button — it is the neutral no-button state.
export const BTN_LEVEL = { clust: 'cluster', strand: 'strand', line: 'domain', ends: 'end', xover: 'xover' }
export const LEVEL_BTN = { cluster: 'clust', strand: 'strand', domain: 'line', end: 'ends', xover: 'xover' }

/**
 * Read the drill-v2 feature flag. Drill-v2 is now the DEFAULT (flipped 2026-06-06);
 * opt OUT via `localStorage NADOC_DRILL_V2='false'` or `?drillv2=0`.
 */
export function isDrillV2() {
  try {
    if (typeof localStorage !== 'undefined') {
      const v = localStorage.getItem('NADOC_DRILL_V2')
      if (v === 'false') return false
      if (v === 'true')  return true
    }
  } catch { /* localStorage may be unavailable */ }
  try {
    if (typeof location !== 'undefined' && new URLSearchParams(location.search).get('drillv2') === '0') return false
  } catch { /* no location in some test envs */ }
  return true
}

/** Coerce any value to a valid level, defaulting unknowns to `default`. */
export function normalizeLevel(level) {
  return LEVELS.includes(level) ? level : 'default'
}

/** Tab transition: from anywhere → first cycle level, then around the cycle. */
export function nextTabLevel(cur) {
  const i = TAB_CYCLE.indexOf(cur)
  return i < 0 ? TAB_CYCLE[0] : TAB_CYCLE[(i + 1) % TAB_CYCLE.length]
}

/** Filter-button toggle: clicking the engaged level turns it off (→ default). */
export function toggleLevel(cur, level) {
  const lv = normalizeLevel(level)
  return cur === lv ? 'default' : lv
}

/**
 * Decide the hover-preview target — the leaf a further click WOULD select, shown
 * with a red preview glow (vs the green selection glow). Pure gate so it unit-tests
 * without the scene/raycast.
 *
 * Preview ONLY when: drill-v2 is on, the active level is `default`, a STRAND is
 * selected (mode 'strand' — not yet drilled to a leaf), and the hovered element
 * belongs to THAT selected strand. A bead previews the would-be end/nucleotide; a
 * cone previews the would-be crossover; an arc previews the would-be crossover for
 * the thin inter-helix crossover line (whose cone is hidden, so the arc is the only
 * pickable target).
 *
 * @param {{drillV2:boolean, selLevel:string, mode:string, strandId:*, hit:object|null}} o
 * @returns {{kind:'bead', entry:object} | {kind:'cone', cone:object} | {kind:'arc', arc:object} | null}
 */
/**
 * Decide WHAT element type a Ctrl-drag lasso captures.
 *
 * Pure resolver shared by `_finalizeLasso` so the lasso's "what am I selecting"
 * truth is testable without the scene. Returns a flag bag the lasso loop reads:
 *   { strands, domains, ends, beadLevel, cluster, xover, overhangs, loops, skips }
 * (`beadLevel` = capture EVERY bead in the rect, not just 5'/3' termini.)
 *
 * Legacy (drillV2 false): an active auto-drill `drillType` type-locks the capture
 * to that level's element; otherwise the `selectableTypes` gates decide.
 *
 * Drill-v2 (drillV2 true): the engaged `selLevel` is the single source of truth —
 * the lasso captures the SAME element type a click at that level would select
 * (default→strand, cluster→cluster, domain→domain, end→bead, xover→crossover).
 * This is the fix for the "Tab to ends, lasso grabs a cluster" bug — see ISSUE-4
 * Phase 3-filter-audit. Overhangs/loops/skips are visibility gates, not levels, so
 * they are not lasso-capturable in v2.
 *
 * @param {{drillV2:boolean, selLevel:string, drillType:string|null, selectableTypes:object}} o
 */
export function lassoCaptureType({ drillV2, selLevel, drillType, selectableTypes }) {
  const st = selectableTypes ?? {}
  if (drillV2) {
    const lv = normalizeLevel(selLevel)
    return {
      strands:   lv === 'default' || lv === 'strand',
      domains:   lv === 'domain',
      ends:      lv === 'end',
      beadLevel: false,            // v2 'end' captures 5'/3' termini only (user decision)
      cluster:   lv === 'cluster',
      xover:     lv === 'xover',
      overhangs: false,            // visibility gates, not levels — not lasso-capturable in v2
      loops:     false,
      skips:     false,
    }
  }
  return {
    strands:   drillType ? drillType === 'strand' : !!st.strands,
    domains:   drillType ? drillType === 'domain' : !!st.domains,
    ends:      drillType ? drillType === 'bead'   : !!st.ends,
    beadLevel: drillType === 'bead',
    cluster:   drillType === 'cluster',
    xover:     drillType ? drillType === 'xover'  : !!st.crossoverArcs,
    overhangs: drillType ? false : !!st.overhangs,
    loops:     drillType ? false : !!st.loops,
    skips:     drillType ? false : !!st.skips,
  }
}

export function hoverPreviewTarget({ drillV2, selLevel, mode, strandId, hit }) {
  if (!drillV2 || selLevel !== 'default' || mode !== 'strand' || !hit) return null
  if (hit.kind === 'bead') {
    return hit.entry?.nuc?.strand_id === strandId ? { kind: 'bead', entry: hit.entry } : null
  }
  if (hit.kind === 'cone') {
    return hit.cone?.strandId === strandId ? { kind: 'cone', cone: hit.cone } : null
  }
  if (hit.kind === 'arc') {
    return hit.arc?.strandId === strandId ? { kind: 'arc', arc: hit.arc } : null
  }
  return null
}
