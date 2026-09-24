/** Resolve painted extrusion in an empty part or one unambiguous source plane.
 * Existing geometry needs explicit frame/end/placement resolution; it must never
 * silently become a second, overlapping independent frame at the origin.
 */
export function buildPaintedExtrusionPlan(config, design, revision) {
  const refuse = reason => ({ accepted: false, reason, plan: null })
  if (!design?.id || !Number.isSafeInteger(revision) || revision < 0) {
    return refuse('document_revision_required')
  }
  const authored = ['helices', 'strands', 'overhangs', 'protein_assets',
    'protein_attachments', 'nanoparticles', 'extensions', 'crossovers', 'forced_ligations']
  const placement = config.freeform_placement
  if (placement && !design.helices?.length) return refuse('initial_default_plane_required')
  let sourceFrame = null
  if (!placement && authored.some(field => design[field]?.length)) {
    // The plane control identifies a source only when exactly one matching frame
    // exists. Legacy/unframed helices require migration before this can be safe.
    const frames = design.lattice_frames ?? []
    if (!design.helices?.length || design.helices.some(h =>
      !h.lattice_frame_id || !frames.some(f => f.id === h.lattice_frame_id))) {
      return refuse('source_frame_required')
    }
    const matches = frames.filter(f => f.plane === config.extrude_from)
    if (matches.length !== 1) return refuse(matches.length ? 'source_frame_ambiguous' : 'source_plane_mismatch')
    sourceFrame = matches[0]
    if ((design.cluster_transforms ?? []).filter(c => c.id === sourceFrame.placement_cluster_id).length !== 1) {
      return refuse('source_placement_required')
    }
    const occupied = new Set(design.helices.filter(h => h.lattice_frame_id === sourceFrame.id)
      .map(h => JSON.stringify(h.grid_pos)))
    if (config.painted_footprint?.cells?.some(cell => occupied.has(JSON.stringify(cell)))) {
      return refuse('painted_cell_occupied')
    }
  }
  if (!config.painted_footprint?.cells?.length) return refuse('paint_cells_required')
  if (config.painted_footprint.lattice_type !== design.lattice_type) return refuse('lattice_mismatch')
  if (!config.length_bp) return refuse('length_required')
  if (config.strand_filter !== 'both') return refuse('strand_filter_unsupported')
  if (!['XY', 'XZ', 'YZ'].includes(config.extrude_from)) return refuse('source_plane_required')
  const args = {
    expected_design_id: design.id, expected_revision: revision,
    ...(sourceFrame ? { source_frame_id: sourceFrame.id } : {}),
    cells: config.painted_footprint.cells.map(cell => [...cell]),
    length_bp: config.direction_sign * config.length_bp,
    plane: config.extrude_from, translation_nm: placement ? [...placement.translation_nm] : [0, 0, 0],
    rotation_xyzw: placement ? [...placement.rotation_xyzw] : [0, 0, 0, 1],
  }
  return {
    accepted: true, reason: 'ready_read_only',
    plan: {
      kind: 'extrude_frame', targetIdentity: `document:${design.id}`,
      preflight: { apiMethod: 'validateFrameExtrusion', arguments: structuredClone(args) },
      commit: { apiMethod: 'addFrameExtrusion', arguments: structuredClone(args) },
      lifecycle: { previewAuthority: 'native_read_only_geometry', cancel: 'discard_descriptor', undo: 'desktop_feature_log' },
    },
  }
}
