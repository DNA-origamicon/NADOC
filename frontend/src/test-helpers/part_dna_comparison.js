import { DNA_RECORD_COLUMNS } from '../features/part_dna_comparison_codec.js'
import { comparisonEnvelope } from './part_comparison.js'

// Fixed accepted native slab authority from helix_renderer.native_placement.test;
// translated copies exercise transport/rendering only, not molecular generation.
export function dnaRecord(index = 0) {
  const shift = position => position.map((v, i) => v + (i === 2 ? index * .34 : 0))
  return { helix_id: 'h', bp_index: index, direction: 'FORWARD', copy_k: 0,
    strand_id: 's', strand_type: 'scaffold', domain_index: 0,
    is_five_prime: index === 0, is_three_prime: index === 1, overhang_id: null,
    is_reference: false, is_flexible_segment: false, is_unpaired: true,
    placement_source: 'native-full-o5-v1',
    backbone_position: shift([-.645612580161337, -.5515026802631344, -.0152]),
    base_position: shift([-.23972062915295275, -.20218550877476973, .0326]),
    base_normal: [.8444255998882265, .5255463335640475, -.10366512205556659], axis_tangent: [0, 0, 1],
    slab_position: shift([-.3811934359011157, -.3239392921967217, .0003]),
    slab_quaternion: [.3433681770212042, .6181409992947685, .6181409992947685, .3433681770212042],
    helical_site: { axis_point: [0, 0, index * .34], radial_hat: [1, 0, 0], azimuth_rad: 0, groove_offset_rad: 0, phase_roll_rad: 0 } }
}

export const dnaRow = record => DNA_RECORD_COLUMNS.map(field => record[field])

export function dnaComponent() {
  return { component_version: 2, representation: 'native-full-v1', units: 'nm',
    nucleotides: [dnaRow(dnaRecord(0)), dnaRow(dnaRecord(1))],
    helix_axes: [{ helix_id: 'h', start: [0, 0, 0], end: [0, 0, .34], samples: [],
      segments: [{ strand_id: 's', domain_index: 0, ovhg_id: null, bp_lo: 0, bp_hi: 1,
        start: [0, 0, 0], end: [0, 0, .34], domain_ids: [{ strand_id: 's', domain_index: 0 }] }] }],
    display_topology: { helices: [{ id: 'h', length_bp: 2, bp_start: 0,
      axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: .34 },
      direction: 'FORWARD', grid_pos: null, lattice_frame_id: null, loop_skips: [] }],
    strands: [{ id: 's', strand_type: 'scaffold', sequence: null, color: null, is_reference: false,
      domains: [{ helix_id: 'h', start_bp: 0, end_bp: 1, direction: 'FORWARD', overhang_id: null, binds_overhang_id: null }] }],
    overhangs: [], cluster_transforms: [], deformations: [], crossovers: [], forced_ligations: [] },
    bounds_nm: { minimum: [-1, -1, -.1], maximum: [1, 1, 1] } }
}

export function dnaEnvelope() {
  const value = comparisonEnvelope()
  value.projection_version = 2; value.scope = 'ordinary-dna-uncoated-particles-free-proteins-v2'
  value.coverage.presentation_policy = 'all_authored_opaque_except_reference_strands'
  value.published.dna = dnaComponent(); value.proposed.dna = dnaComponent()
  return value
}
