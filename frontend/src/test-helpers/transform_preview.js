import { dnaComponent, dnaRecord } from './part_dna_comparison.js'

/** Tiny transport fixture, based on the existing accepted native Full records. */
export function transformComponent() {
  const value = dnaComponent()
  Object.assign(value, { component_kind: 'transform-preview-dna', component_version: 1,
    required_renderers: [], nucleotides: [dnaRecord(0), dnaRecord(1)] })
  const topology = value.display_topology
  Object.assign(topology.helices[0], { native_residues: [], native_source: null, phase_offset: 0,
    twist_per_bp_rad: .598647933434055, label: null })
  Object.assign(topology.strands[0], { custom_scaffold_length: null, name: null, notes: null })
  for (const key of ['lattice_frames', 'nucleotide_transforms', 'cluster_joints', 'cluster_join_constraints',
    'overhang_connections', 'overhang_bindings', 'connection_versions', 'duplexes', 'flexible_segment_marks',
    'flexible_connections', 'extensions', 'staple_groups', 'photoproduct_junctions', 'crossover_constraints']) topology[key] = []
  topology.cluster_transforms = [{ id: 'placement', name: 'Placement', is_default: false,
    helix_ids: ['h'], domain_ids: [], translation: [0, 0, 0], rotation: [0, 0, 0, 1], pivot: [0, 0, 0],
    parent_cluster_id: null, overhang_duplex_driver_id: null, color: null, opacity: 1, auto_created: false }]
  return value
}

export function transformPacket({ prepare = true, geometry = true, envelope = false } = {}) {
  const before = transformComponent(), candidate = transformComponent(), topology = candidate.display_topology
  const inputs = { _proof_version: 1, cluster_id: 'placement', translation: [0, 0, 0], rotation: [0, 0, 0, 1], pivot: [0, 0, 0] }
  const context = Object.fromEntries(['lattice_frames', 'helices', 'strands', 'cluster_transforms', 'cluster_joints',
    'cluster_join_constraints', 'flexible_segment_marks', 'flexible_connections', 'crossovers', 'forced_ligations',
    'extensions', 'nucleotide_transforms', 'group_organization', 'photoproduct_junctions'].map(key => [key, structuredClone(topology[key])]))
  Object.assign(context, { inputs, lattice_type: 'SQUARE' })
  const control_state = { ...structuredClone(context), flexible_gates: { placement: {
    cluster_id: 'placement', gate: false, n_crossings: 0, rigid_blocking: [],
  } },
    placement_constraints: [{ cluster_id: 'placement', rotation_points: [], tethers: [], movable_links: [] }],
    frame_provenance: { joint_axes: {}, rotation_points: {}, placement_poses: {
      placement: { parent_cluster_id: null, frame: 'native-design' },
    } } }
  const result = { projection_version: 1, family: 'transform', command_kind: 'cluster_op', feature_id: 'feature',
    evaluated_command_kind: 'cluster_op',
    stage: 'feature', source_equivalence_checked: false, downstream_evaluated: false, physical_validity: false,
    control_state, candidate: geometry ? candidate : null }
  if (prepare) Object.assign(result, { before, control_context: { ...context,
    placement_upgrade: { upgrade_to: 'placement-poses-v1', expected_definition_sha256: 'a'.repeat(64) } } })
  if (envelope) Object.assign(result, { preview_id: 'preview', expected_design_id: 'design', expected_revision: 2,
    lease_id: 'lease', doc_id: 'doc', request_sequence: 0, remaining_seconds: 25 })
  return result
}
