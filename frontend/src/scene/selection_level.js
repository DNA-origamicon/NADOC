// Selection-level model (ISSUE-4 Phase 2 "drill v2").
//
// Collapses the three overlapping legacy mechanisms — auto-drill ladder, manual
// filter pins, and the Tab drill-lock — into ONE concept: an active
// `selectionLevel`. There is exactly one engaged level at a time, so the old
// "red border means two different things" ambiguity disappears.
//
//   default → 1st click selects the STRAND; 2nd click on the selected strand
//             selects the leaf UNDER THE CURSOR (bead → end | cone → xover).
//             Cluster & domain are NOT in the click path.
//   cluster | domain | end | xover → every click selects at that FIXED level.
//
// Tab cycles cluster → domain → end → xover → cluster (strand/default are OUT of
// the cycle). Escape returns to `default`. The #select-filter level buttons drive
// the SAME state (clust/strand/line/ends/xover).
//
// This whole model is behind the `NADOC_DRILL_V2` flag (localStorage or
// `?drillv2=1`); when off the legacy auto-drill/lock paths run unchanged.
//
// Everything here is pure (no DOM / scene / store) so it unit-tests directly.

export const LEVELS    = ['default', 'cluster', 'domain', 'end', 'xover']
// Tab cycles only the four engaged levels — never strand/default.
export const TAB_CYCLE = ['cluster', 'domain', 'end', 'xover']

// Filter-button dataKey ↔ selectionLevel. The `strand` button maps to `default`
// (the strand-first click), so the row reads as one coherent level selector.
export const BTN_LEVEL = { clust: 'cluster', strand: 'default', line: 'domain', ends: 'end', xover: 'xover' }
export const LEVEL_BTN = { default: 'strand', cluster: 'clust', domain: 'line', end: 'ends', xover: 'xover' }

/** Read the drill-v2 feature flag (localStorage `NADOC_DRILL_V2`='true' or `?drillv2=1`). */
export function isDrillV2() {
  try {
    if (typeof localStorage !== 'undefined' && localStorage.getItem('NADOC_DRILL_V2') === 'true') return true
  } catch { /* localStorage may be unavailable */ }
  try {
    if (typeof location !== 'undefined' && new URLSearchParams(location.search).get('drillv2') === '1') return true
  } catch { /* no location in some test envs */ }
  return false
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
