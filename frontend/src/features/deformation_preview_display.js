/** Closed feature-stage display inputs. This validates; it never constructs a Design. */
import { fail, finite, integer, text, shape, vector, list, unique } from './part_comparison_validation.js'
import { validateDeformationPreviewComponent } from './part_dna_comparison_model.js'

const FLAGS = ['projection_version', 'stage', 'source_equivalence_checked', 'downstream_evaluated', 'physical_validity', 'feasibility']
const ENVELOPE = ['preview_id', 'expected_design_id', 'expected_revision', 'feature_id', 'lease_id', 'doc_id', 'deformation_id', 'request_sequence', 'remaining_seconds']
const OP_FIELDS = ['id', 'type', 'targets', 'target_ranges', 'plane_a_bp', 'plane_b_bp', 'affected_helix_ids', 'cluster_ids', 'params']
const PROVENANCE = ['id', 'type', 'target_ranges', 'plane_a_bp', 'plane_b_bp', 'affected_helix_ids']
const HELIX = ['id', 'bp_start', 'length_bp', 'axis_start', 'axis_end']
const STRAND = ['id', 'strand_type', 'domains', 'is_reference']
const GROUP = ['id', 'name', 'is_default', 'helix_ids', 'domain_ids']
const nullableNumber = value => { if (value !== null && !finite(value)) fail('invalid deformation feedback number') }
const bp = value => { if (!Number.isSafeInteger(value) || Math.abs(value) > 1e6) fail('invalid deformation address') }

// Walk only the bounded, already validated topology on the right. No generic
// traversal/copy/encoding of the nucleotide graph is needed for control parity.
function same(value, expected) {
  if (Array.isArray(expected)) {
    list(value, expected.length)
    if (value.length !== expected.length) fail('incomplete deformation control inventory')
    for (let i = 0; i < expected.length; i++) same(value[i], expected[i])
  } else if (expected !== null && typeof expected === 'object') {
    const keys = Object.keys(expected); shape(value, keys)
    for (const key of keys) same(value[key], expected[key])
  } else if (value !== expected) fail('deformation controls disagree with native display')
}

function fields(value, expected, names) {
  for (const name of names) same(value[name], expected[name])
}

function referenceIds(values, owners) {
  list(values, 512)
  for (const id of values) { text(id); if (!owners.has(id)) fail('unresolved deformation control reference') }
}

function textBudget() {
  let remaining = 500000 // Same conservative string ceiling as the server's 2 MB graph budget.
  return value => { text(value, remaining, true); remaining -= value.length }
}

function feasibility(value, string) {
  shape(value, ['status', 'op_type', 'local_bp_per_turn', 'max_abs_delta_per_cell', 'n_cells',
    'requested_twist_deg', 'max_twist_deg', 'requested_radius_nm', 'min_bend_radius_nm', 'message'])
  if (!['ok', 'warn', 'block'].includes(value.status) || !['bend', 'twist'].includes(value.op_type)
      || !finite(value.local_bp_per_turn) || !finite(value.max_abs_delta_per_cell) || !integer(value.n_cells)) fail('invalid native deformation feedback')
  for (const key of ['requested_twist_deg', 'max_twist_deg', 'requested_radius_nm', 'min_bend_radius_nm']) nullableNumber(value[key])
  string(value.message)
}

function targets(values, strands, groups) {
  if (values === null) return
  list(values, 512)
  if (!values.length) fail('empty deformation target selection')
  for (const value of values) {
    if (value?.kind === 'domain') {
      const camel = Object.hasOwn(value, 'strandId') || Object.hasOwn(value, 'domainIndex')
      shape(value, camel ? ['kind', 'strandId', 'domainIndex'] : ['kind', 'strand_id', 'domain_index'])
      const id = camel ? value.strandId : value.strand_id, index = camel ? value.domainIndex : value.domain_index
      text(id)
      if (!integer(index) || !strands.get(id)?.domains[index]) fail('unresolved deformation target domain')
    } else {
      shape(value, ['kind', 'id']); text(value.id)
      const owners = value.kind === 'strand' ? strands : value.kind === 'cluster' ? groups : null
      if (!owners?.has(value.id)) fail('unresolved deformation target owner')
    }
  }
}

function parameters(op, projected, priorIds, string) {
  const p = op.params
  if (op.type === 'bend') {
    shape(p, ['kind', 'curvature_deg_per_bp', 'direction_deg',
      ...['endpoints', 'midpoint', 'polymer_circle_count'].filter(key => Object.hasOwn(p ?? {}, key))])
    if (p.kind !== 'bend' || !finite(p.curvature_deg_per_bp) || !finite(p.direction_deg)) fail('invalid bend controls')
    if (Object.hasOwn(p, 'endpoints')) {
      list(p.endpoints, 2)
      if (p.endpoints.length !== 2) fail('incomplete bend endpoints')
      for (const point of p.endpoints) vector(point, 3)
    }
    if (Object.hasOwn(p, 'midpoint')) vector(p.midpoint, 3)
    if (Object.hasOwn(p, 'polymer_circle_count') && (!integer(p.polymer_circle_count) || p.polymer_circle_count < 1)) fail('invalid polymer circle control')
    same(p.curvature_deg_per_bp, projected.curvature_deg_per_bp)
    same(p.polymer_circle_count, projected.polymer_circle_count)
  } else if (op.type === 'twist') {
    shape(p, ['kind', 'total_degrees', 'degrees_per_nm'])
    if (p.kind !== 'twist') fail('invalid twist controls')
    nullableNumber(p.total_degrees); nullableNumber(p.degrees_per_nm)
  } else if (op.type === 'sweep') {
    shape(p, ['kind', 'points_nm', 'origin_nm', 'initial_rotation', 'initial_tangent', 'point_frames',
      'warning_bps', 'auto_loop_skips', 'loop_skip_warnings', 'preceding_op_ids', 'direction', 'start_step',
      'steps', 'path_length_nm', 'bp_positions_nm', 'bp_frames'])
    if (p.kind !== 'sweep' || ![1, -1].includes(p.direction) || !integer(p.steps) || p.steps < 1 || p.steps > 1024
        || !finite(p.path_length_nm) || p.path_length_nm <= 0 || typeof p.auto_loop_skips !== 'boolean'
        || p.bp_positions_nm !== null || p.bp_frames !== null) fail('unsupported retained sweep controls')
    list(p.points_nm, 256)
    if (p.points_nm.length < 2) fail('incomplete retained sweep path')
    for (const point of p.points_nm) vector(point, 3)
    vector(p.origin_nm, 3); vector(p.initial_rotation, 9)
    if (p.initial_tangent !== null) vector(p.initial_tangent, 3)
    if (p.point_frames !== null) {
      list(p.point_frames, 256)
      for (const frame of p.point_frames) if (frame !== null) vector(frame, 9)
    }
    list(p.warning_bps, 1024); p.warning_bps.forEach(bp); bp(p.start_step)
    list(p.loop_skip_warnings, 1024); p.loop_skip_warnings.forEach(string)
    referenceIds(p.preceding_op_ids, priorIds)
    fields(p, projected, ['direction', 'start_step'])
  } else fail('unsupported deformation control operation')
}

function operation(op, projected, strands, groups, priorIds, string) {
  shape(op, OP_FIELDS)
  fields(op, projected, PROVENANCE)
  if (op.plane_a_bp > op.plane_b_bp || (op.type !== 'sweep' && op.plane_a_bp === op.plane_b_bp)) fail('invalid deformation control window')
  targets(op.targets, strands, groups); referenceIds(op.cluster_ids, groups)
  parameters(op, projected.params, priorIds, string)
}

function controls(value, before, candidate, feedback, string) {
  shape(value, ['helices', 'strands', 'cluster_transforms', 'deformations', 'forced_ligations', 'selected_operation', 'capabilities'])
  const prefix = before.display_topology, output = candidate.display_topology
  for (const key of ['helices', 'strands', 'cluster_transforms', 'deformations', 'forced_ligations']) {
    list(value[key], prefix[key].length)
    if (value[key].length !== prefix[key].length) fail('incomplete fixed-prefix controls')
    unique(value[key])
  }
  for (const key of ['helices', 'strands', 'overhangs', 'cluster_transforms', 'crossovers', 'forced_ligations']) same(output[key], prefix[key])
  for (let i = 0; i < value.helices.length; i++) {
    shape(value.helices[i], HELIX); fields(value.helices[i], prefix.helices[i], HELIX)
  }
  const strands = new Map(value.strands.map(item => [item.id, item]))
  for (let i = 0; i < value.strands.length; i++) {
    const strand = value.strands[i]; shape(strand, [...STRAND, 'notes']); fields(strand, prefix.strands[i], STRAND)
    if (strand.notes !== null) string(strand.notes)
  }
  const groups = new Map(value.cluster_transforms.map(item => [item.id, item]))
  for (let i = 0; i < value.cluster_transforms.length; i++) {
    const group = value.cluster_transforms[i]
    shape(group, [...GROUP, 'parent_cluster_id', 'translation', 'rotation', 'pivot']); fields(group, prefix.cluster_transforms[i], GROUP)
    vector(group.translation, 3); vector(group.rotation, 4); vector(group.pivot, 3)
    const visited = new Set([group.id])
    let parent = group.parent_cluster_id
    while (parent !== null) {
      text(parent)
      if (!groups.has(parent) || visited.has(parent)) fail('unresolved or cyclic deformation group parent')
      visited.add(parent); parent = groups.get(parent).parent_cluster_id
    }
  }
  same(value.forced_ligations, prefix.forced_ligations)
  if (output.deformations.length !== prefix.deformations.length + 1) fail('incomplete feature-stage deformation provenance')
  const priorIds = new Set()
  for (let i = 0; i < value.deformations.length; i++) {
    same(output.deformations[i], prefix.deformations[i])
    operation(value.deformations[i], prefix.deformations[i], strands, groups, priorIds, string)
    priorIds.add(value.deformations[i].id)
  }
  const op = value.selected_operation
  operation(op, output.deformations.at(-1), strands, groups, priorIds, string)
  if (priorIds.has(op.id) || op.type !== feedback.op_type) fail('ambiguous selected deformation control')
  shape(value.capabilities, ['change_targets', 'change_clusters', 'native_feasibility', 'polymer_circle_inputs'])
  if (value.capabilities.change_targets !== false || value.capabilities.change_clusters !== (op.targets === null && op.target_ranges === null)
      || value.capabilities.native_feasibility !== true || value.capabilities.polymer_circle_inputs !== true) fail('unsupported deformation control capability')
}

/** Same-object validation; controller separately owns exact origin/sequence CAS. */
export function validateDeformationPreviewDisplay(value, { prepare, requireEnvelope = false } = {}) {
  if (typeof prepare !== 'boolean' || typeof requireEnvelope !== 'boolean') fail('explicit deformation display stage required')
  const hasEnvelope = ENVELOPE.some(key => Object.hasOwn(value ?? {}, key))
  if (requireEnvelope && !hasEnvelope) fail('missing deformation host envelope')
  shape(value, [...FLAGS, 'candidate', ...(prepare ? ['before', 'control_context'] : []), ...(hasEnvelope ? ENVELOPE : [])])
  if (value.projection_version !== 1 || value.stage !== 'feature' || value.source_equivalence_checked !== false
      || value.downstream_evaluated !== false || value.physical_validity !== false) fail('unsupported deformation display claim')
  if (hasEnvelope) {
    for (const key of ['preview_id', 'expected_design_id', 'feature_id', 'lease_id', 'deformation_id']) text(value[key])
    text(value.doc_id, 1024)
    if (!integer(value.expected_revision) || !integer(value.request_sequence)
        || !finite(value.remaining_seconds) || value.remaining_seconds < 0) fail('invalid deformation host envelope')
  }
  const string = textBudget()
  feasibility(value.feasibility, string)
  if (prepare) validateDeformationPreviewComponent(value.before)
  if (value.candidate !== null) {
    validateDeformationPreviewComponent(value.candidate)
    const selected = value.candidate.display_topology.deformations.at(-1)
    if (!selected || selected.type !== value.feasibility.op_type
        || (hasEnvelope && selected.id !== value.deformation_id)) fail('candidate does not identify the selected deformation')
  } else if (prepare) fail('missing initial deformation display')
  if (prepare) controls(value.control_context, value.before, value.candidate, value.feasibility, string)
  return value
}
