import { dnaComponent } from './part_dna_comparison.js'

export const SWEEP_ID = '33333333-3333-4333-8333-333333333333'
export const sweepInputs = () => ({ sweep_id: SWEEP_ID, _proof_version: 1, cells: [[0, 0]],
  points_nm: [[0, 0, 0], [0, 0, .34]], orientations_deg: [null, null], plane: 'XY', strand_filter: 'both',
  ligate_adjacent: true, source_helix_id: null, source_end: 'end', detach_source: false,
  expected_design_id: null, expected_revision: null })
const basis = () => [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
export const sweepMetadata = () => ({ source_detached: false, origin_nm: [0, 0, 0],
  path_nm: [[0, 0, 0], [0, 0, .34]], points_nm: [[0, 0, 0], [0, 0, .34]],
  point_rotation: basis(), orientation_basis: basis(), point_bases: [basis(), basis()],
  source_frame: { grid_origin: [0, 0, 0], frame_right: [1, 0, 0], frame_up: [0, 1, 0], axis_dir: [0, 0, 1] },
  helix_paths_nm: [[[0, 0, 0], [0, 0, .34]]], cross_section_nm: [[0, 0]], direction: 1,
  length_nm: .34, length_bp: 2, total_new_bp: 2,
  feasibility: { status: 'ok', warning_segments: [], ranges_nm: [], max_delta_per_cell: 0,
    limit_per_cell: 2, cell_bp: 21, message: '', scope: 'Bending demand only; not a stability or torsional feasibility prediction.' } })
export function sweepPacket({ prepare = true, envelope = false } = {}) {
  const component = () => ({ ...dnaComponent(), component_kind: 'deformation-preview-dna', component_version: 2 })
  const before = component(); before.display_topology.helices[0].grid_pos = [0, 0]
  const value = { projection_version: 1, stage: 'feature', source_equivalence_checked: false,
    downstream_evaluated: false, physical_validity: false, candidate: null,
    sweep_preview: sweepMetadata() }
  if (prepare) Object.assign(value, { before, control_context: { inputs: sweepInputs(), lattice_type: 'HONEYCOMB', lattice_frames: [],
    helices: before.display_topology.helices.map(({ id, grid_pos, lattice_frame_id, bp_start, length_bp, axis_start, axis_end }) =>
      ({ id, label: '', grid_pos, lattice_frame_id, bp_start, length_bp, axis_start, axis_end })) } })
  if (envelope) Object.assign(value, { preview_id: '11111111-1111-4111-8111-111111111111', expected_design_id: 'part', expected_revision: 7,
    feature_id: 'feature', lease_id: '22222222-2222-4222-8222-222222222222', doc_id: 'doc',
    deformation_id: `sweep_${SWEEP_ID}`, request_sequence: 0, remaining_seconds: 60 })
  return value
}
