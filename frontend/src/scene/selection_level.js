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
// This is the only selection model — the legacy auto-drill ladder / manual filter
// pins / Tab drill-lock were physically deleted 2026-06-06 (there is no flag any
// more; v2 is simply the behavior).
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
 * Preview ONLY when: the active level is `default`, a STRAND is selected (mode
 * 'strand' — not yet drilled to a leaf), and the hovered element belongs to THAT
 * selected strand. A bead previews the would-be end/nucleotide; a
 * cone previews the would-be crossover; an arc previews the would-be crossover for
 * the thin inter-helix crossover line (whose cone is hidden, so the arc is the only
 * pickable target).
 *
 * @param {{selLevel:string, mode:string, strandId:*, hit:object|null}} o
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
 * The engaged `selLevel` is the single source of truth — the lasso captures the
 * SAME element type a click at that level would select (default/strand→strand,
 * cluster→cluster, domain→domain, end→bead, xover→crossover). This is the fix for
 * the "Tab to ends, lasso grabs a cluster" bug (ISSUE-4 Phase 3-filter-audit).
 * Overhangs/loops/skips are visibility gates, not levels, so they are not
 * lasso-capturable. The scaffold/staple gates are applied separately in the lasso
 * loop, NOT here.
 *
 * @param {{selLevel:string}} o
 */
export function lassoCaptureType({ selLevel }) {
  const lv = normalizeLevel(selLevel)
  return {
    strands:   lv === 'default' || lv === 'strand',
    domains:   lv === 'domain',
    ends:      lv === 'end',
    beadLevel: false,            // 'end' captures 5'/3' termini only (user decision)
    cluster:   lv === 'cluster',
    xover:     lv === 'xover',
    overhangs: false,            // visibility gates, not levels — not lasso-capturable
    loops:     false,
    skips:     false,
  }
}

export function hoverPreviewTarget({ selLevel, mode, strandId, hit }) {
  if (selLevel !== 'default' || mode !== 'strand' || !hit) return null
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
