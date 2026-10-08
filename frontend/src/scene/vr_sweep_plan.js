/** Sweep uses the desktop's canonical lattice centroid and model-space deltas. */
import { resolveExtrudeSourcePlane } from '../ui/extrude_source_plane.js'

export function buildVRSweepPlan(config, design, revision) {
  const refuse = reason => ({ accepted: false, reason, plan: null })
  if (!design?.id || !Number.isSafeInteger(revision) || revision < 0) return refuse('document_revision_required')
  if (!config.painted_footprint.cells.length) return refuse('paint_cells_required')
  if (config.painted_footprint.lattice_type !== design.lattice_type) return refuse('lattice_mismatch')
  if (config.points_nm.length < 2) return refuse('path_points_required')
  const frames = new Map((design.lattice_frames ?? []).map(f => [f.id, f]))
  const occupied = new Set((design.helices ?? []).flatMap(h => {
    const frame = frames.get(h.lattice_frame_id)
    const resolved = frame ? { plane: frame.plane, reason: 'geometry' } : resolveExtrudeSourcePlane({ helices: [h] })
    const address = /^h_(XY|XZ|YZ)_(-?\d+)_(-?\d+)(?:_|$)/.exec(h.id ?? '')
    const cell = h.grid_pos ?? (address ? [Number(address[2]), Number(address[3])] : null)
    return cell && resolved.reason === 'geometry' && resolved.plane === config.extrude_from ? [JSON.stringify(cell)] : []
  }))
  if (config.painted_footprint.cells.some(cell => occupied.has(JSON.stringify(cell))))
    return refuse('painted_cell_occupied')
  const args = { ...(config.orientations_deg == null ? {} : { orientations_deg: structuredClone(config.orientations_deg) }), expected_design_id: design.id, expected_revision: revision,
    cells: config.painted_footprint.cells.map(cell => [...cell]),
    points_nm: config.points_nm.map(point => [...point]), plane: config.extrude_from,
    strand_filter: config.strand_filter, ligate_adjacent: config.ligate_adjacent }
  return { accepted: true, reason: 'ready_read_only', plan: {
    kind: 'sweep', targetIdentity: `document:${design.id}`,
    preflight: { apiMethod: 'previewSweep', arguments: structuredClone(args) },
    commit: { apiMethod: 'createSweep', arguments: structuredClone(args) },
    lifecycle: { previewAuthority: 'native_read_only_geometry', cancel: 'discard_descriptor', undo: 'desktop_feature_log' },
  } }
}
