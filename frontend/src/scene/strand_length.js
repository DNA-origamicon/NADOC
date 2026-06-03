/**
 * Strand-length helpers extracted from main.js, which had three near-duplicate
 * implementations. Pure: plain design/strand/helix objects only — no scene/store.
 * Unit-tested in strand_length.test.js.
 *
 *   strandLengthNt           — canonical, loop-skip-aware (helixById lookup object)
 *   strandLengthNtFromDesign — same, building the helix lookup from a Design
 *   strandDomainNt           — domain-span sum only, IGNORES loop/skip deltas
 */

/**
 * Length in nucleotides, loop/skip-aware. `helixById` is a plain object keyed by
 * helix id ({ [helixId]: helix }); each helix may carry `loop_skips`.
 * (Was `_strandLen` in main.js.)
 */
export function strandLengthNt(strand, helixById) {
  return (strand.domains ?? []).reduce((sum, d) => {
    const h = helixById[d.helix_id]
    const lo = Math.min(d.start_bp, d.end_bp), hi = Math.max(d.start_bp, d.end_bp)
    const skip = (h?.loop_skips ?? [])
      .filter(ls => ls.bp_index >= lo && ls.bp_index <= hi)
      .reduce((s, ls) => s + ls.delta, 0)
    return sum + (Math.abs(d.end_bp - d.start_bp) + 1) + skip
  }, 0)
}

/** Loop/skip-aware length, building the helix lookup from a Design.
 *  (Was `_strandLength` in main.js.) */
export function strandLengthNtFromDesign(strand, design) {
  const helixById = Object.fromEntries((design?.helices ?? []).map(h => [h.id, h]))
  return strandLengthNt(strand, helixById)
}

/** Sum of domain spans only — does NOT apply loop/skip deltas.
 *  (Was `_strandNt` in main.js.) */
export function strandDomainNt(strand) {
  let t = 0
  for (const d of strand.domains ?? []) t += Math.abs((d.end_bp ?? 0) - (d.start_bp ?? 0)) + 1
  return t
}
