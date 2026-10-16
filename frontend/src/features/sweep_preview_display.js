/** Closed, same-object validation of the native Sweep feature-stage display. */
import { fail, finite, integer, text, shape, vector, list, unique } from './part_comparison_validation.js'
import { validateDeformationPreviewComponent } from './part_dna_comparison_model.js'

const ENVELOPE = ['preview_id', 'expected_design_id', 'expected_revision', 'feature_id', 'lease_id', 'doc_id', 'deformation_id', 'request_sequence', 'remaining_seconds']
const HELIX = ['id', 'label', 'grid_pos', 'lattice_frame_id', 'bp_start', 'length_bp', 'axis_start', 'axis_end']
const INPUTS = ['sweep_id', '_proof_version', 'cells', 'points_nm', 'orientations_deg', 'plane', 'strand_filter', 'ligate_adjacent', 'source_helix_id', 'source_end', 'detach_source']
const PLANE = ['XY', 'XZ', 'YZ']
function points(values, maximum, dimensions = 3) { list(values, maximum); for (const point of values) vector(point, dimensions) }
function basis(value) { list(value, 3); if (value.length !== 3) fail('incomplete Sweep frame'); for (const row of value) vector(row, 3) }
function xyz(value) { shape(value, ['x', 'y', 'z']); vector([value.x, value.y, value.z], 3) }
function equal(a, b) {
  if (Array.isArray(b)) { list(a, b.length); if (a.length !== b.length) fail('incomplete Sweep controls'); b.forEach((v, i) => equal(a[i], v)) }
  else if (b && typeof b === 'object') { shape(a, Object.keys(b)); for (const key of Object.keys(b)) equal(a[key], b[key]) }
  else if (a !== b) fail('Sweep controls disagree with fixed native prefix')
}
function inputs(value, helices) {
  shape(value, [...INPUTS, ...['expected_design_id', 'expected_revision'].filter(key => Object.hasOwn(value ?? {}, key))])
  text(value.sweep_id)
  if (value._proof_version !== 1 || !PLANE.includes(value.plane) || !['both', 'scaffold', 'staples'].includes(value.strand_filter)
      || !['start', 'end'].includes(value.source_end) || typeof value.ligate_adjacent !== 'boolean' || typeof value.detach_source !== 'boolean') fail('unsupported Sweep inputs')
  points(value.cells, 16, 2)
  if (!value.cells.length || value.cells.some(cell => cell.some(v => !Number.isSafeInteger(v) || Math.abs(v) > 10000))
      || new Set(value.cells.map(cell => cell.join(','))).size !== value.cells.length) fail('invalid Sweep cells')
  points(value.points_nm, 256)
  if (value.points_nm.length < 2 || value.points_nm.some(point => point.some(v => Math.abs(v) > 10000))) fail('invalid Sweep points')
  if (value.orientations_deg !== null) {
    list(value.orientations_deg, value.points_nm.length)
    if (value.orientations_deg.length !== value.points_nm.length) fail('incomplete Sweep orientations')
    for (const angles of value.orientations_deg) if (angles !== null) { vector(angles, 3); if (angles.some(v => Math.abs(v) > 360)) fail('invalid Sweep angles') }
  }
  if (value.source_helix_id !== null) { text(value.source_helix_id); if (!helices.has(value.source_helix_id)) fail('missing fixed-prefix Sweep source') }
  if (value.expected_design_id != null) text(value.expected_design_id)
  if (value.expected_revision != null && (!integer(value.expected_revision) || value.expected_design_id == null)) fail('invalid saved Sweep expectation')
}
function metadata(value) {
  shape(value, ['source_detached', 'feasibility', 'source_frame', 'origin_nm', 'points_nm', 'path_nm', 'point_rotation',
    'orientation_basis', 'point_bases', 'helix_paths_nm', 'cross_section_nm', 'direction', 'length_nm', 'length_bp', 'total_new_bp'])
  if (typeof value.source_detached !== 'boolean' || ![1, -1].includes(value.direction)
      || !finite(value.length_nm) || value.length_nm <= 0 || !integer(value.length_bp) || value.length_bp < 1
      || value.length_bp > 1024 || !integer(value.total_new_bp) || value.total_new_bp > 1024) fail('invalid native Sweep extent')
  vector(value.origin_nm, 3); points(value.points_nm, 256); points(value.path_nm, 2048)
  if (value.points_nm.length < 2 || value.path_nm.length < 2) fail('incomplete native Sweep path')
  basis(value.point_rotation); basis(value.orientation_basis)
  list(value.point_bases, value.points_nm.length)
  if (value.point_bases.length !== value.points_nm.length) fail('incomplete native Sweep point frames')
  value.point_bases.forEach(basis)
  list(value.helix_paths_nm, 16); value.helix_paths_nm.forEach(path => points(path, 2048))
  points(value.cross_section_nm, 16, 2)
  shape(value.source_frame, ['grid_origin', 'frame_right', 'frame_up', 'axis_dir'])
  Object.values(value.source_frame).forEach(point => vector(point, 3))
  const f = value.feasibility
  shape(f, ['status', 'warning_segments', 'ranges_nm', 'max_delta_per_cell', 'limit_per_cell', 'cell_bp', 'message', 'scope'])
  if (!['ok', 'warning'].includes(f.status) || !finite(f.max_delta_per_cell) || !finite(f.limit_per_cell)
      || !integer(f.cell_bp) || f.cell_bp < 1) fail('invalid native Sweep feasibility')
  text(f.message, 32768, true); text(f.scope, 4096)
  list(f.warning_segments, value.path_nm.length)
  if (f.warning_segments.some(i => !integer(i) || i >= value.path_nm.length - 1)) fail('invalid Sweep warning segment')
  points(f.ranges_nm, 2048, 2)
}
function controls(value, before, native, envelope) {
  shape(value, ['inputs', 'lattice_type', 'helices', 'lattice_frames'])
  if (!['SQUARE', 'HONEYCOMB'].includes(value.lattice_type)) fail('unsupported Sweep lattice')
  const topology = before.display_topology
  list(value.helices, 16); unique(value.helices)
  if (value.helices.length !== topology.helices.length) fail('incomplete fixed-prefix Sweep helices')
  const helices = new Set(value.helices.map(h => h.id)), owners = new Set(topology.cluster_transforms.map(c => c.id))
  list(value.lattice_frames, 16); unique(value.lattice_frames)
  const frames = new Set(value.lattice_frames.map(f => f.id))
  for (const frame of value.lattice_frames) {
    shape(frame, ['id', 'plane', 'placement_cluster_id']); text(frame.id, 128); text(frame.placement_cluster_id, 128)
    if (!PLANE.includes(frame.plane) || !owners.has(frame.placement_cluster_id)) fail('missing Sweep frame placement')
  }
  value.helices.forEach((helix, i) => {
    shape(helix, HELIX); if (helix.label !== null) text(helix.label, 32768, true)
    if (helix.grid_pos !== null) { vector(helix.grid_pos, 2); if (!helix.grid_pos.every(Number.isSafeInteger)) fail('invalid Sweep grid') }
    if (helix.lattice_frame_id !== null && !frames.has(helix.lattice_frame_id)) fail('missing Sweep lattice frame')
    xyz(helix.axis_start); xyz(helix.axis_end)
    for (const key of HELIX.filter(key => key !== 'label')) equal(helix[key], topology.helices[i][key])
  })
  inputs(value.inputs, helices)
  if (envelope && envelope.deformation_id !== `sweep_${value.inputs.sweep_id}`) fail('wrong Sweep feature identity')
  if (value.inputs.points_nm.length !== native.points_nm.length) fail('incomplete native Sweep controls')
}

/** The shared controller checks exact origin and sequence separately. No graph clone. */
export function validateSweepPreviewDisplay(value, { prepare, requireEnvelope = false } = {}) {
  if (typeof prepare !== 'boolean' || typeof requireEnvelope !== 'boolean') fail('explicit Sweep display stage required')
  const envelope = ENVELOPE.some(key => Object.hasOwn(value ?? {}, key))
  if (requireEnvelope && !envelope) fail('missing Sweep host envelope')
  shape(value, ['projection_version', 'stage', 'source_equivalence_checked', 'downstream_evaluated', 'physical_validity', 'candidate', 'sweep_preview',
    ...(prepare ? ['before', 'control_context'] : []), ...(envelope ? ENVELOPE : [])])
  if (value.projection_version !== 1 || value.stage !== 'feature' || value.source_equivalence_checked !== false
      || value.downstream_evaluated !== false || value.physical_validity !== false) fail('unsupported Sweep display claim')
  if (envelope) {
    for (const key of ['preview_id', 'expected_design_id', 'feature_id', 'lease_id', 'deformation_id']) text(value[key])
    text(value.doc_id, 1024)
    if (!integer(value.expected_revision) || !integer(value.request_sequence) || !finite(value.remaining_seconds) || value.remaining_seconds < 0) fail('invalid Sweep host envelope')
  }
  metadata(value.sweep_preview)
  if (prepare) validateDeformationPreviewComponent(value.before)
  if (value.candidate !== null) validateDeformationPreviewComponent(value.candidate)
  else if (prepare) fail('missing initial Sweep candidate')
  if (prepare) controls(value.control_context, value.before, value.sweep_preview, envelope ? value : null)
  return value
}
