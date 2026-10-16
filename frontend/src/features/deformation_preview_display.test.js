import { describe, expect, it, vi } from 'vitest'
import { validateDeformationPreviewDisplay } from './deformation_preview_display.js'
import { dnaComponent } from '../test-helpers/part_dna_comparison.js'

const component = () => ({ ...dnaComponent(), component_kind: 'deformation-preview-dna', component_version: 2 })
const bend = () => ({ id: 'bend', type: 'bend', targets: null, target_ranges: null,
  plane_a_bp: 0, plane_b_bp: 1, affected_helix_ids: ['h'], cluster_ids: [],
  params: { kind: 'bend', curvature_deg_per_bp: .5, direction_deg: 20 } })
const provenance = op => ({ id: op.id, type: op.type, affected_helix_ids: [...op.affected_helix_ids],
  target_ranges: op.target_ranges, plane_a_bp: op.plane_a_bp, plane_b_bp: op.plane_b_bp,
  params: op.type === 'bend' ? { curvature_deg_per_bp: op.params.curvature_deg_per_bp,
    ...(op.params.polymer_circle_count === undefined ? {} : { polymer_circle_count: op.params.polymer_circle_count }) }
    : op.type === 'sweep' ? { direction: op.params.direction, start_step: op.params.start_step } : {} })
const scope = op => ({ id: op.id, affected_helix_ids: op.affected_helix_ids, target_ranges: op.target_ranges })
const host = () => ({ preview_id: '11111111-1111-4111-8111-111111111111', expected_design_id: 'part', expected_revision: 7,
  feature_id: 'feature', lease_id: '22222222-2222-4222-8222-222222222222', doc_id: 'doc', deformation_id: 'bend',
  request_sequence: 0, remaining_seconds: 60 })

function packet({ prepare = true, geometry = true } = {}) {
  const before = component(), candidate = component(), operation = bend()
  candidate.display_topology.deformations = [provenance(operation)]
  const result = { selected_scope: scope(operation), projection_version: 2, stage: 'feature', source_equivalence_checked: false,
    downstream_evaluated: false, physical_validity: false, feasibility: { status: 'ok', op_type: 'bend',
      local_bp_per_turn: 10.5, max_abs_delta_per_cell: 0, n_cells: 0, requested_twist_deg: null,
      max_twist_deg: null, requested_radius_nm: 20, min_bend_radius_nm: null, message: '' },
    candidate: geometry ? candidate : null }
  if (prepare) Object.assign(result, { before, control_context: {
    helices: before.display_topology.helices.map(({ id, bp_start, length_bp, axis_start, axis_end }) => ({ id, bp_start, length_bp, axis_start, axis_end })),
    strands: before.display_topology.strands.map(({ id, domains, strand_type, is_reference }) => ({ id, domains, strand_type, is_reference, notes: 'Polymerization connector: authored note' })),
    group_organization: null, cluster_transforms: [], deformations: [], forced_ligations: [], selected_operation: operation,
    capabilities: { change_targets: false, change_clusters: true, native_feasibility: true, polymer_circle_inputs: true },
  } })
  return result
}

function addGroups(value) {
  const group = { id: 'group', name: 'Arm', is_default: false, helix_ids: ['h'], domain_ids: [],
    parent_cluster_id: null, translation: [1, 2, 3], rotation: [0, 0, 0, 1], pivot: [0, 0, 0] }
  const child = { ...group, id: 'child', parent_cluster_id: 'group', domain_ids: [{ strand_id: 's', domain_index: 0 }] }
  value.control_context.cluster_transforms = [group, child]
  for (const pane of [value.before, value.candidate]) pane.display_topology.cluster_transforms = [group, child].map(
    ({ id, name, is_default, helix_ids, domain_ids }) => ({ id, name, is_default, helix_ids, domain_ids, color: null, auto_created: false }))
  value.control_context.selected_operation.cluster_ids = ['child']
}

function addPriorSweep(value) {
  const sweep = { ...bend(), id: 'sweep', type: 'sweep', params: { kind: 'sweep',
    points_nm: [[0, 0, 0], [0, 0, .34]], origin_nm: [0, 0, 0], initial_rotation: [1, 0, 0, 0, 1, 0, 0, 0, 1],
    initial_tangent: [0, 0, 1], point_frames: null, warning_bps: [], auto_loop_skips: false,
    loop_skip_warnings: [], preceding_op_ids: [], direction: 1, start_step: 0, steps: 1, path_length_nm: .34,
    bp_positions_nm: null, bp_frames: null } }
  value.control_context.deformations = [sweep]
  value.before.display_topology.deformations = [provenance(sweep)]
  value.candidate.display_topology.deformations.unshift(provenance(sweep))
}

describe('closed native deformation display and control envelope', () => {
  it.each([
    ['Prepare', { prepare: true }], ['Evaluate', { prepare: false }], ['controls only', { prepare: false, geometry: false }],
  ])('accepts the actual %s shape without replacing or mutating its graph', (_name, options) => {
    const value = packet(options), before = structuredClone(value)
    expect(validateDeformationPreviewDisplay(value, options)).toBe(value)
    expect(value).toEqual(before)
  })

  it('admits one complete host envelope while leaving exact origin authority to the controller', () => {
    const value = { ...packet(), ...host() }
    expect(validateDeformationPreviewDisplay(value, { prepare: true, requireEnvelope: true })).toBe(value)
    expect(() => validateDeformationPreviewDisplay(packet(), { prepare: true, requireEnvelope: true })).toThrow()
    expect(() => validateDeformationPreviewDisplay(packet({ prepare: false }), { prepare: false, requireEnvelope: true })).toThrow()
  })

  it('preserves native warning/block verdicts without treating them as a replay proof', () => {
    for (const status of ['warn', 'block']) {
      const value = packet(); value.feasibility.status = status
      expect(validateDeformationPreviewDisplay(value, { prepare: true }).feasibility.status).toBe(status)
    }
  })

  it('retains full group poses and parents, strand notes, prior sweep inputs and polymer seams', () => {
    const value = packet(); addGroups(value); addPriorSweep(value)
    const ligation = { id: 'seam', three_prime_helix_id: 'h', three_prime_bp: 1, three_prime_direction: 'FORWARD',
      five_prime_helix_id: 'h', five_prime_bp: 0, five_prime_direction: 'FORWARD', extra_bases: null, is_periodic_seam: true }
    value.control_context.forced_ligations = [ligation]
    for (const pane of [value.before, value.candidate]) pane.display_topology.forced_ligations = [ligation]
    value.control_context.selected_operation.params.polymer_circle_count = 4
    value.candidate.display_topology.deformations.at(-1).params.polymer_circle_count = 4
    expect(validateDeformationPreviewDisplay(value, { prepare: true })).toBe(value)
  })

  it.each(['snake', 'camel'])('accepts existing %s domain selectors and frozen exact ranges', spelling => {
    const value = packet(), op = value.control_context.selected_operation
    op.targets = [spelling === 'snake' ? { kind: 'domain', strand_id: 's', domain_index: 0 }
      : { kind: 'domain', strandId: 's', domainIndex: 0 }]
    op.target_ranges = [{ helix_id: 'h', start_bp: 0, end_bp: 1, direction: 'FORWARD', strand_id: 's', domain_index: 0 }]
    value.candidate.display_topology.deformations[0] = provenance(op)
  value.selected_scope = scope(op)
    value.control_context.capabilities.change_clusters = false
    expect(validateDeformationPreviewDisplay(value, { prepare: true })).toBe(value)
  })

  it('does not clone or serialize the large display graph during slider validation', () => {
    const value = packet({ prepare: false }), encode = JSON.stringify
    const clone = vi.spyOn(globalThis, 'structuredClone').mockImplementation(() => { throw new Error('Graph clone') })
    const serialize = vi.spyOn(JSON, 'stringify').mockImplementation(item => {
      if (item === value || item === value.candidate || item === value.candidate.nucleotides) throw new Error('Graph encoding')
      return encode(item)
    })
    try { expect(validateDeformationPreviewDisplay(value, { prepare: false })).toBe(value) }
    finally { clone.mockRestore(); serialize.mockRestore() }
  })

  it.each([
    ['unknown envelope field', d => { d.design = {} }],
    ['partial host identity', d => { d.preview_id = host().preview_id }],
    ['unbounded host identity', d => { Object.assign(d, host(), { feature_id: 'x'.repeat(257) }) }],
    ['wrong version', d => { d.projection_version = 1 }],
    ['wrong stage', d => { d.stage = 'final' }],
    ['source proof claim', d => { d.source_equivalence_checked = true }],
    ['suffix proof claim', d => { d.downstream_evaluated = true }],
    ['physical proof claim', d => { d.physical_validity = true }],
    ['missing before pane', d => { delete d.before }],
    ['missing candidate pane', d => { d.candidate = null }],
    ['missing occupied record', d => { d.candidate.nucleotides.pop() }],
    ['unsupported feasibility', d => { d.feasibility.status = 'verified' }],
    ['unknown feasibility field', d => { d.feasibility.geometry = {} }],
    ['nonfinite feasibility', d => { d.feasibility.requested_radius_nm = Infinity }],
    ['wrong operation feedback', d => { d.feasibility.op_type = 'twist' }],
    ['missing control strand', d => { d.control_context.strands = [] }],
    ['changed control domain', d => { d.control_context.strands = structuredClone(d.control_context.strands); d.control_context.strands[0].domains[0].end_bp = 0 }],
    ['unresolved group member', d => { addGroups(d); d.control_context.cluster_transforms[0].helix_ids = ['missing'] }],
    ['group parent cycle', d => { addGroups(d); d.control_context.cluster_transforms[0].parent_cluster_id = 'child' }],
    ['malformed group pose', d => { addGroups(d); d.control_context.cluster_transforms[0].rotation = [0, 0, 1] }],
    ['nontext strand notes', d => { d.control_context.strands[0].notes = {} }],
    ['unbounded strand notes', d => { d.control_context.strands[0].notes = 'x'.repeat(500001) }],
    ['unknown control collection', d => { d.control_context.input_sources = {} }],
    ['unknown selected parameter', d => { d.control_context.selected_operation.params.saved_geometry = [] }],
    ['mismatched selected identity', d => { d.control_context.selected_operation.id = 'elsewhere' }],
    ['selected operation among priors', d => { d.control_context.deformations = [d.control_context.selected_operation] }],
    ['malformed retained sweep frame', d => { addPriorSweep(d); d.control_context.deformations[0].params.initial_rotation = [1] }],
    ['unresolved preceding operation', d => { addPriorSweep(d); d.control_context.deformations[0].params.preceding_op_ids = ['missing'] }],
    ['omitted prior display provenance', d => { addPriorSweep(d); d.before.display_topology.deformations = [] }],
    ['unsupported retarget capability', d => { d.control_context.capabilities.change_targets = true }],
    ['fake capability type', d => { d.control_context.capabilities.change_clusters = 'yes' }],
  ])('refuses %s before exposing controls or geometry', (_name, mutate) => {
    const value = packet(); mutate(value)
    expect(() => validateDeformationPreviewDisplay(value, { prepare: true })).toThrow()
  })

  it('Evaluate never accepts repeated prefix controls or silently ignores an extra pane', () => {
    expect(() => validateDeformationPreviewDisplay(packet(), { prepare: false })).toThrow()
    const value = packet({ prepare: false }); value.before = component()
    expect(() => validateDeformationPreviewDisplay(value, { prepare: false })).toThrow()
  })
})

function namedPacket() {
  const value = packet(); addGroups(value)
  const organization = { version: 1, groups: [{ id: 'child', name: 'Named selection', helix_ids: ['h'], domain_ids: [],
    color: null, opacity: 1, is_default: false, auto_created: false }] }
  value.control_context.group_organization = structuredClone(organization)
  for (const pane of [value.before, value.candidate]) pane.display_topology.group_organization = structuredClone(organization)
  const op = value.control_context.selected_operation
  op.targets = [{ kind: 'part_group', id: 'child' }]
  op.target_ranges = [{ helix_id: 'h', start_bp: 0, end_bp: 1, direction: 'FORWARD', strand_id: 's', domain_index: 0 }]
  value.candidate.display_topology.deformations[0] = provenance(op)
  value.selected_scope = scope(op)
  value.control_context.capabilities = { change_targets: true, change_clusters: false, native_feasibility: true, polymer_circle_inputs: true }
  return value
}

it('admits named organizational controls with an independent same-named placement scope', () => {
  const value = namedPacket(), before = structuredClone(value)
  expect(validateDeformationPreviewDisplay(value, { prepare: true })).toBe(value)
  expect(value).toEqual(before)
})

it.each([
  ['missing named group', d => { d.control_context.selected_operation.targets[0].id = 'group' }],
  ['duplicate targets', d => { d.control_context.selected_operation.targets.push({ ...d.control_context.selected_operation.targets[0] }) }],
  ['replacement metadata', d => { d.control_context.group_organization.groups[0].name = 'Other' }],
  ['wrong capability', d => { d.control_context.capabilities.change_targets = false }],
  ['mixed editable targets', d => { d.control_context.selected_operation.targets.push({ kind: 'strand', id: 's' }) }],
])('refuses named selection %s', (_name, mutate) => {
  const value = namedPacket(); mutate(value)
  expect(() => validateDeformationPreviewDisplay(value, { prepare: true })).toThrow()
})

it('retained primitive selectors are historical with frozen ranges but selected controls stay live', () => {
  const value = packet(), old = { ...bend(), id: 'old', targets: [{ kind: 'domain', strand_id: 'old-strand', domain_index: 7 }],
    target_ranges: [{ helix_id: 'h', start_bp: 0, end_bp: 5, direction: 'FORWARD', strand_id: 'old-strand', domain_index: 7 }] }
  value.control_context.deformations = [old]
  value.before.display_topology.deformations = [provenance(old)]
  value.candidate.display_topology.deformations.unshift(provenance(old))
  expect(validateDeformationPreviewDisplay(value, { prepare: true })).toBe(value)
  value.control_context.selected_operation.targets = old.targets
  value.control_context.selected_operation.target_ranges = old.target_ranges
  value.candidate.display_topology.deformations[1] = provenance(value.control_context.selected_operation)
  value.selected_scope = scope(value.control_context.selected_operation)
  value.control_context.capabilities.change_clusters = false
  expect(() => validateDeformationPreviewDisplay(value, { prepare: true })).toThrow(/target/)
})

it('prior named references remain live even when ranges retain old domain provenance', () => {
  const value = namedPacket(), old = { ...bend(), id: 'old', targets: [{ kind: 'part_group', id: 'missing' }],
    target_ranges: [{ helix_id: 'h', start_bp: 0, end_bp: 5, direction: 'FORWARD', strand_id: 'old', domain_index: 7 }] }
  value.control_context.deformations = [old]
  value.before.display_topology.deformations = [provenance(old)]
  value.candidate.display_topology.deformations.unshift(provenance(old))
  expect(() => validateDeformationPreviewDisplay(value, { prepare: true })).toThrow(/target/)
})


it('controls-only evaluation carries exact bounded guide scope without invented live owners', () => {
  const value = packet({ prepare: false, geometry: false })
  value.selected_scope.target_ranges = [{ helix_id: 'h', start_bp: 0, end_bp: 5, direction: 'FORWARD', strand_id: 'historical', domain_index: 20 }]
  expect(validateDeformationPreviewDisplay(value, { prepare: false })).toBe(value)
  value.selected_scope.target_ranges[0].domain_index = null
  expect(() => validateDeformationPreviewDisplay(value, { prepare: false })).toThrow()
})

it.each([
  ['extra guide data', d => { d.selected_scope.axes = [] }],
  ['scope identity', d => { d.selected_scope.id = 'other' }],
  ['scope range parity', d => { d.selected_scope.target_ranges = [] }],
  ['scope missing helix', d => { d.selected_scope.affected_helix_ids = ['missing'] }],
])('refuses %s before displaying candidate or guides', (_name, mutate) => {
  const value = { ...packet(), ...host() }; mutate(value)
  expect(() => validateDeformationPreviewDisplay(value, { prepare: true, requireEnvelope: true })).toThrow()
})
