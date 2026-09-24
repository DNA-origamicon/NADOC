/** Canonical coordinates for a framed end, separate from its rendered locator. */
export function canonicalVREndSource(helix, continuationBp, design) {
  const frames = (design?.lattice_frames ?? []).filter(f => f.id === helix?.lattice_frame_id)
  if (frames.length !== 1) return null
  const frame = frames[0]
  const component = { XY:'z', XZ:'y', YZ:'x' }[frame.plane]
  const placements = (design.cluster_transforms ?? []).filter(c =>
    c.helix_ids?.includes(helix.id) || c.domain_ids?.some(ref =>
      design.strands?.find(s => s.id===ref.strand_id)?.domains?.[ref.domain_index]?.helix_id===helix.id))
  if (!component || placements.length !== 1 || placements[0].id !== frame.placement_cluster_id ||
      !placements[0].helix_ids?.includes(helix.id)) return null
  if (!Number.isSafeInteger(helix.bp_start) || !Number.isSafeInteger(helix.length_bp) ||
      helix.length_bp < 1 || !Number.isSafeInteger(continuationBp)) return null
  // A framed source must retain a canonical straight axis in its local plane.
  const start = helix.axis_start, end = helix.axis_end
  if (!['x','y','z'].every(c => Number.isFinite(start?.[c]) && Number.isFinite(end?.[c])) ||
      end[component] <= start[component] ||
      ['x','y','z'].some(c => c !== component && Math.abs(end[c]-start[c]) > 1e-8)) return null
  if (continuationBp < helix.bp_start || continuationBp > helix.bp_start+helix.length_bp) return null
  return {
    sourceFrameId:frame.id, plane:frame.plane,
    offsetNm:start[component] + (continuationBp-helix.bp_start) *
      (end[component]-start[component])/helix.length_bp,
  }
}
