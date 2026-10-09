/** A size-one circle reconnects this part's own seam; there is no next copy
 * to illustrate. Use the stored deformation scope, never proximity between
 * strands (nearby strands can still be independent, open polymer ends). */
export function selfClosingPolymerSeam(design, seam) {
  if (!seam.is_periodic_seam) return false
  const sides = ['three_prime', 'five_prime']
  return (design?.deformations ?? []).some(op => {
    if (op.type !== 'bend' || op.params?.polymer_circle_count !== 1 ||
        !(op.params.curvature_deg_per_bp > 0)) return false
    const lo = Math.min(seam.three_prime_bp, seam.five_prime_bp)
    const hi = Math.max(seam.three_prime_bp, seam.five_prime_bp)
    if (Math.min(hi, op.plane_b_bp) <= Math.max(lo, op.plane_a_bp)) return false
    return sides.every(side => {
      const helix = seam[`${side}_helix_id`], bp = seam[`${side}_bp`], direction = seam[`${side}_direction`]
      if (op.affected_helix_ids?.length && !op.affected_helix_ids.includes(helix)) return false
      // Frozen ranges override legacy whole-helix scope, including an empty set.
      return op.target_ranges == null || op.target_ranges.some(r =>
        r.helix_id === helix && r.direction === direction && r.start_bp <= bp && bp <= r.end_bp)
    })
  })
}
