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
//   cluster | domain | end | xover | base → every click selects at that FIXED level.
//
// `base` is the finest grain: ONE backbone bead, spanning all five bead renderers
// (backbone/5′ cubes/extension tails, fluorophore tips, extra crossover bases, flexible
// ssDNA arcs, ss-linker bridges). It has its own key-based pool — see `base_ref.js`.
//
// Tab cycles strand → domain → end → xover → base → none(default) → strand. Escape
// returns to `default`. The #select-filter level buttons drive the SAME state
// (clust/strand/line/ends/xover/base); no button lit = `default`. CLUSTER is reached via
// its button ONLY — removed from the Tab cycle 2026-06-07 (rarely used: only for
// repositioning in dynamic parts, after staple routing is mostly done).
//
// This is the only selection model — the legacy auto-drill ladder / manual filter
// pins / Tab drill-lock were physically deleted 2026-06-06 (there is no flag any
// more; v2 is simply the behavior).
//
// Everything here is pure (no DOM / scene / store) so it unit-tests directly.

export const LEVELS    = ['default', 'cluster', 'strand', 'domain', 'end', 'xover', 'base']
// Tab cycles strand → domain → end → xover → base → none(default) → strand. Cluster is
// NOT in the cycle (button-only access, 2026-06-07). `base` sits last, immediately before
// the wrap: it is the finest grain there is, and the position mirrors its button sitting
// to the right of xover. `default` = no button engaged = the drill ladder (2026-06-06).
export const TAB_CYCLE = ['strand', 'domain', 'end', 'xover', 'base', 'default']

// Filter-button dataKey ↔ selectionLevel. `strand` is now a DISTINCT fixed level
// (every click → whole strand), separate from `default` (no button = drill ladder).
// `default` has NO button — it is the neutral no-button state.
export const BTN_LEVEL = { clust: 'cluster', strand: 'strand', line: 'domain', ends: 'end', xover: 'xover', base: 'base' }
export const LEVEL_BTN = { cluster: 'clust', strand: 'strand', domain: 'line', end: 'ends', xover: 'xover', base: 'base' }

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
 *   { strands, domains, ends, beadLevel, cluster, xover, base, overhangs, loops, skips }
 *
 * The engaged `selLevel` is the single source of truth — the lasso captures the
 * SAME element type a click at that level would select (default/strand→strand,
 * cluster→cluster, domain→domain, end→bead, xover→crossover, base→one bead). This is
 * the fix for the "Tab to ends, lasso grabs a cluster" bug (ISSUE-4 Phase 3-filter-audit).
 *
 * `beadLevel` vs `base` — NOT the same flag, don't merge them. `beadLevel` ("capture
 * every bead in the rect, not just 5'/3' termini") is a hard-coded `false` recording a
 * user decision about the END level; it drains into `_ctrlBeads`, the MEASUREMENT pool
 * that measurement_tool.js expects to hold exactly 2. `base` is the base level's own
 * flag and drains into the key-based base pool. Leave `beadLevel` alone.
 *
 * EXCEPTIONS — the overhang and extension filters: when one is on, the lasso captures
 * only that filtered type, taking precedence over the engaged
 * level — the same precedence a plain click and a Ctrl+click already give the overhang
 * filter (2026-06-07). loops/skips remain non-lasso-capturable visibility gates. The
 * scaffold/staple gates are applied separately in the lasso loop, NOT here.
 *
 * @param {{selLevel:string, overhangFilter?:boolean, extensionFilter?:boolean}} o
 */
export function lassoCaptureType({ selLevel, overhangFilter = false, extensionFilter = false }) {
  // Overhang filter active → overhangs only (exclusive mode, not a level), matching
  // the plain-click / Ctrl+click precedence.
  if (overhangFilter) {
    return {
      strands: false, domains: false, ends: false, beadLevel: false,
      cluster: false, xover: false, base: false, overhangs: true, extensions: false, loops: false, skips: false,
    }
  }
  if (extensionFilter) {
    return {
      strands: false, domains: false, ends: false, beadLevel: false,
      cluster: false, xover: false, base: false, overhangs: false, extensions: true, loops: false, skips: false,
    }
  }
  const lv = normalizeLevel(selLevel)
  return {
    strands:   lv === 'default' || lv === 'strand',
    domains:   lv === 'domain',
    ends:      lv === 'end',
    beadLevel: false,            // 'end' captures 5'/3' termini only (user decision)
    cluster:   lv === 'cluster',
    xover:     lv === 'xover',
    base:      lv === 'base',    // individual beads, into the key-based base pool
    overhangs: false, extensions: false, // gates, not levels
    loops:     false,
    skips:     false,
  }
}

/** Return only tail entries owned by the selected extension IDs. */
export function extensionSelectionEntries(entries = [], extensionIds = []) {
  const ids = new Set(extensionIds)
  return entries.filter(entry => ids.has(entry?.nuc?.extension_id))
}

/** Right-click acts on the selected extension set only when the hit belongs to it. */
export function extensionContextIds(hitExtensionId, selectedExtensionIds = []) {
  if (!hitExtensionId) return []
  return selectedExtensionIds.includes(hitExtensionId) ? [...selectedExtensionIds] : [hitExtensionId]
}

/**
 * Cluster multi-select toggle rule. A cluster's presence is decided by the CLUSTER id
 * pool, never by its member strands: two clusters can share a strand (a staple that
 * bridges them), so "are all its strands selected?" answers the wrong question.
 * The member strands are what the highlight renders, so they ride along.
 *
 * @param {{clusterIds?:string[], strandIds?:string[], clusterId:string, memberStrandIds?:string[]}} o
 * @returns {{clusterIds:string[], strandIds:string[]}}
 */
export function toggleClusterSelection({ clusterIds = [], strandIds = [], clusterId, memberStrandIds = [] }) {
  if (!clusterId) return { clusterIds: [...clusterIds], strandIds: [...strandIds] }
  if (clusterIds.includes(clusterId)) {
    const drop = new Set(memberStrandIds)
    return {
      clusterIds: clusterIds.filter(id => id !== clusterId),
      strandIds:  strandIds.filter(id => !drop.has(id)),
    }
  }
  return {
    clusterIds: [...clusterIds, clusterId],
    strandIds:  [...new Set([...strandIds, ...memberStrandIds])],
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
