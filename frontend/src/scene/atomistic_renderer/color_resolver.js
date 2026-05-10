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
  C_HIGHLIGHT,
  C_DIM_FACTOR,
  _dimColor,
} from './atom_palette.js'

/**
 * Classify an atom given the current selection and return its colour as 0xRRGGBB.
 *
 * Priority cascade (coarsest to finest):
 *   multi-lasso → strand → domain → nucleotide
 *
 * @param {object}  ctx       { colorMode, strandColors:Map, baseColors:Map }
 * @param {object}  atom      atom record
 * @param {object|null} sel   current selection
 * @param {string[]}    multiIds  multi-lasso strand ids
 */
export function colorForAtom(ctx, atom, sel, multiIds) {
  const el      = atom.element
  const cpk     = ELEMENTS[el]?.color ?? 0x505050
  const dimCpk  = _dimColor(cpk, C_DIM_FACTOR)

  // Multi-lasso selection overrides everything
  if (multiIds.length > 0) {
    return multiIds.includes(atom.strand_id) ? C_HIGHLIGHT : dimCpk
  }

  if (!sel) return cpk   // no selection — full CPK

  const type = sel.type
  const data = sel.data ?? {}

  if (type === 'strand') {
    return atom.strand_id === data.strand_id ? C_HIGHLIGHT : dimCpk
  }

  if (type === 'domain') {
    if (atom.strand_id !== data.strand_id) return dimCpk
    // Exact domain match: same helix + same direction within the strand
    const inDomain = atom.helix_id  === data.helix_id
                  && atom.direction === data.direction
    return inDomain ? C_HIGHLIGHT : _dimColor(cpk, 0.40)
  }

  if (type === 'nucleotide') {
    if (atom.strand_id !== data.strand_id) return dimCpk
    if (atom.bp_index  === data.bp_index
     && atom.direction === data.direction)       return C_HIGHLIGHT
    // Same strand, same domain (direction match): medium
    if (atom.direction === data.direction)       return _dimColor(cpk, 0.55)
    // Same strand, other domain
    return _dimColor(cpk, 0.30)
  }

  if (type === 'cone') {
    // Cones belong to a strand; highlight that strand
    return atom.strand_id === data.strand_id ? C_HIGHLIGHT : dimCpk
  }

  // base colour by mode; extra-base atoms always use their strand colour
  if (ctx.colorMode === 'strand' || atom.aux_helix_id) {
    return ctx.strandColors.get(atom.strand_id) ?? cpk
  }
  if (ctx.colorMode === 'base') {
    const k = `${atom.strand_id}:${atom.bp_index}:${atom.direction}`
    return ctx.baseColors.get(k) ?? ctx.strandColors.get(atom.strand_id) ?? cpk
  }
  return cpk
}

/** Resolve the final colour for one atom under the current mode + selection. */
export function resolveAtomColor(ctx, atom, sel, multiIds, hasSelection) {
  const el  = atom.element
  const cpk = ELEMENTS[el]?.color ?? 0x505050
  if (hasSelection) return colorForAtom(ctx, atom, sel, multiIds)
  const isXb = !!atom.aux_helix_id  // extra-base: always strand-coloured
  if (ctx.colorMode === 'strand' || isXb) {
    return ctx.strandColors.get(atom.strand_id) ?? cpk
  }
  if (ctx.colorMode === 'base') {
    const k = `${atom.strand_id}:${atom.bp_index}:${atom.direction}`
    return ctx.baseColors.get(k) ?? ctx.strandColors.get(atom.strand_id) ?? cpk
  }
  return cpk
}
