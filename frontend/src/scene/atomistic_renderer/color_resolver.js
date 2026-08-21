// Atomistic colour resolver — pure helpers extracted from atomistic_renderer.js
// (Refactor 13-F). Classifies an atom's render colour given the current
// selection + mode state.
//
// Leaf module: imports the ancestor leaf `atom_palette.js` only. NO imports
// from `atomistic_renderer.js` or sibling modules under `atomistic_renderer/`
// other than ancestor leaves (substantive precondition #19).
//
// Module-mutable state (`_colorMode`, `_strandColors`, `_baseColors`) lives in
// the parent module per Pass 12-B's surface map; callers pass a `colorCtx`
// object snapshotting those refs into a per-call read-only handle.
// Pass 14+ may relocate the mutable state itself — out of scope for 13-F.

import {
  ELEMENTS,
  DEFAULT_ELEMENT,
  C_HIGHLIGHT,
} from './atom_palette.js'

// A selection descriptor is immutable for the duration of a renderer repaint.
// Compile its array membership tests once and let the WeakMap release the index
// with the descriptor. Atomistic models can contain millions of atoms; doing up
// to five Array.includes/some scans for every atom made selection recolouring
// scale as O(atoms × selected-items).
const _selectionIndexes = new WeakMap()

function _selectionIndex(selection) {
  if (!selection || typeof selection !== 'object') return null
  let index = _selectionIndexes.get(selection)
  if (index) return index
  const domains = new Map()
  for (const domain of selection.domains ?? []) {
    const key = `${domain.strandId}\0${domain.helixId}\0${domain.direction}`
    let intervals = domains.get(key)
    if (!intervals) domains.set(key, intervals = [])
    intervals.push([domain.lo, domain.hi])
  }
  index = {
    extensionIds: new Set(selection.extensionIds ?? []),
    helixIds: new Set(selection.helixIds ?? []),
    strandIds: new Set(selection.strandIds ?? []),
    domains,
    bases: new Set((selection.bases ?? []).map(base =>
      `${base.helix_id}\0${base.bp_index}\0${base.direction}`)),
  }
  _selectionIndexes.set(selection, index)
  return index
}

/**
 * Classify an atom given the current selection and return its colour as 0xRRGGBB.
 *
 * Priority cascade (coarsest to finest):
 *   multi-lasso → strand → domain → nucleotide
 *
 * @param {object}  ctx       { colorMode, strandColors:Map, baseColors:Map, clusterColors:Map }
 * @param {object}  atom      atom record
 * @param {object} selection canonical atom-selection descriptor
 */
export function colorForAtom(ctx, atom, selection) {
  const el      = atom.element
  const cpk     = ELEMENTS[el]?.color ?? DEFAULT_ELEMENT.color
  const normal  = _normalColor(ctx, atom, cpk)

  const selected = _selectionIndex(selection)
  if (selected?.extensionIds.has(atom.extension_id)) return C_HIGHLIGHT
  if (selected?.helixIds.has(atom.helix_id)) return C_HIGHLIGHT
  if (selected?.strandIds.has(atom.strand_id)) return C_HIGHLIGHT
  const intervals = selected?.domains.get(`${atom.strand_id}\0${atom.helix_id}\0${atom.direction}`)
  if (intervals?.some(([lo, hi]) => atom.bp_index >= lo && atom.bp_index <= hi)) return C_HIGHLIGHT
  if (selected?.bases.has(`${atom.helix_id}\0${atom.bp_index}\0${atom.direction}`)) return C_HIGHLIGHT
  return normal
}

/** Normal display colour, including scalar overlays, with no selection treatment. */
function _normalColor(ctx, atom, cpk) {
  if (ctx.scalarColors) {
    const copy = Number(atom.copy_k ?? atom.copy ?? 0)
    const c = (atom.scalar_key ? ctx.scalarColors.get(atom.scalar_key) : null)
      ?? ctx.scalarColors.get(`${atom.helix_id}:${atom.bp_index}:${atom.direction}:${copy}`)
      ?? ctx.scalarColors.get(`${atom.helix_id}:${atom.bp_index}:${atom.direction}`)
    if (c != null) return c
  }
  return _colorByMode(ctx, atom, cpk)
}

/**
 * Unselected colouring: the current mode applied to one atom.
 *
 * Crossover extra bases (`aux_helix_id` set) and strand-extension tails carry the
 * ANCHOR/SOURCE nucleotide's helix/bp/direction, so they have no base-letter key of
 * their own — 'base' mode would paint them with a neighbouring base's letter, and
 * falls back to their strand colour instead.  CPK is per-ELEMENT and needs no key, so
 * these atoms follow it exactly like every other atom.  (They used to be pinned to
 * strand colour in EVERY mode, which made them the one thing on screen that ignored
 * the colouring buttons.)
 */
function _colorByMode(ctx, atom, cpk) {
  // Per-cluster colour is resolved per NUCLEOTIDE, not per strand: a strand can pass
  // through several clusters (the scaffold passes through nearly all of them), so a
  // strand-keyed lookup paints every scaffold atom with one cluster's colour. The map
  // is populated only in cluster-coloring mode, so no mode gate is needed here.
  // Extra-base / extension atoms carry their ANCHOR nucleotide's helix:bp:dir, so they
  // inherit that nucleotide's cluster — which is what you want.
  if (ctx.clusterColors?.size) {
    // Bare-helix fallback covers synthetic `__ext_` helices (see color_util.clusterOfNucKey).
    const c = ctx.clusterColors.get(`${atom.helix_id}:${atom.bp_index}:${atom.direction}`)
      ?? ctx.clusterColors.get(atom.helix_id)
    if (c != null) return c
  }
  if (ctx.colorMode === 'strand') return ctx.strandColors.get(atom.strand_id) ?? cpk
  if (ctx.colorMode === 'base') {
    if (atom.aux_helix_id) return ctx.strandColors.get(atom.strand_id) ?? cpk
    const k = `${atom.strand_id}:${atom.bp_index}:${atom.direction}`
    return ctx.baseColors.get(k) ?? ctx.strandColors.get(atom.strand_id) ?? cpk
  }
  return cpk
}

/** Resolve the final colour for one atom under the current mode + selection. */
export function resolveAtomColor(ctx, atom, selection, hasSelection) {
  const el  = atom.element
  const cpk = ELEMENTS[el]?.color ?? DEFAULT_ELEMENT.color
  if (hasSelection) return colorForAtom(ctx, atom, selection)
  // Scalar overlay (e.g. oxDNA flexibility map): when present and nothing is
  // selected, an atom's nucleotide colour wins over CPK/strand so the heavy rep
  // shows the SAME rigid→flexible ramp as the beads.  Keyed by helix:bp:dir.
  return _normalColor(ctx, atom, cpk)
}
