/**
 * Strand-end resize helpers shared by the 3D end-extrude arrows and the cadnano
 * 2D editor's end-drag.
 *
 * A 1-nt strand's single nucleotide is BOTH the 5′ and 3′ terminus, so neither
 * the 3D arrow nor the 2D end-drag can tell from position alone which end the
 * user means. Historically both defaulted to 5′ — which leaves a stub pinned by a
 * crossover (or the design edge) impossible to resize when its 5′ side is the
 * blocked one. These helpers pick the end that can actually extend.
 */

/**
 * True if the bp immediately beyond `nuc` (in the given direction) is NOT covered
 * by another strand on the same helix+direction — i.e. the end can extend there.
 * @param {{helix_id:string, direction:string, bp_index:number, strand_id:string}} nuc
 * @param {Array} strands              design strands
 * @param {boolean} towardHigherBp     extension direction: true = +1 bp, false = -1 bp
 */
export function adjacentBpFree(nuc, strands, towardHigherBp) {
  const target = nuc.bp_index + (towardHigherBp ? 1 : -1)
  for (const s of (strands ?? [])) {
    if (s.id === nuc.strand_id) continue
    for (const d of s.domains) {
      if (d.helix_id !== nuc.helix_id || d.direction !== nuc.direction) continue
      if (Math.min(d.start_bp, d.end_bp) <= target && target <= Math.max(d.start_bp, d.end_bp)) {
        return false
      }
    }
  }
  return true
}

/**
 * For a 1-nt strand (its single bead is BOTH 5′ and 3′), pick which end to expose
 * for resizing: prioritise the end whose extension direction is free, so a stub
 * pinned on one side by a crossover / design edge is still resizable on the other.
 * When both (or neither) are free, default to 5′ (the historical default).
 *
 * Equivalent to the user's cell-direction framing: a REVERSE cell carries a
 * FORWARD staple whose 5′ extends toward bp−1, so "blocked at bp−1 → use 3′"; a
 * FORWARD cell carries a REVERSE staple whose 5′ extends toward bp+1.
 * @returns {'5p'|'3p'}
 */
export function oneNtResizableEnd(nuc, strands) {
  const fiveTowardHigher = nuc.direction === 'REVERSE'   // 5′ of REVERSE is the high-bp side
  const fiveFree  = adjacentBpFree(nuc, strands, fiveTowardHigher)
  const threeFree = adjacentBpFree(nuc, strands, !fiveTowardHigher)
  if (threeFree && !fiveFree) return '3p'
  return '5p'
}
