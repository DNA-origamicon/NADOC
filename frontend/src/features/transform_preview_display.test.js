// @vitest-environment node
import { describe, expect, it, vi } from 'vitest'
import { validateTransformPreviewDisplay, validateTransformPreviewComponent, consumeValidatedTransformPreviewComponent } from './transform_preview_display.js'
import { compactTransformComponent, transformComponent, transformPacket } from '../test-helpers/transform_preview.js'

// Exercise boundary mechanisms with the original tiny capacities.
vi.mock('./transform_preview_limits.js', () => ({ TRANSFORM_DISPLAY_LIMITS: {
  helices: 16, strands: 128, domains: 256, records: 1024, selectors: 512,
  owners: 32, nativeWork: 4096, axisPoints: 2048, nodes: 200_000, bytes: 2_000_000,
} }))

const nativePose = { translation: [0, 0, 0], rotation: [0, 0, 0, 1], pivot: [0, 0, 0] }
const compound = () => ({ _proof_version: 1, primary_cluster_id: 'placement', selected_cluster_ids: ['placement'],
  poses: [{ cluster_id: 'placement', ...structuredClone(nativePose), parent_cluster_id: null, overhang_duplex_driver_id: null }],
  authoring: { mode: 'free', joint_id: null, fixed_cluster_ids: [], pivot_id: 'centroid' },
  primary_authored_fields: {}, legacy_source: null })
const residue = () => ({ kind: 'base', helix_id: 'h', bp_index: 0, direction: 'FORWARD', ...structuredClone(nativePose) })
function rolePacket(kind) {
  const packet = transformPacket()
  packet.command_kind = packet.evaluated_command_kind = kind
  packet.control_context.placement_upgrade = null
  const inputs = kind === 'placement-poses' ? compound()
    : kind === 'nucleotide-transform-batch' ? { _proof_version: 1, history_seed: '8ea7d453-6e52-4243-8d32-c6331dd134fd', transforms: [residue()] }
      : kind === 'nucleotide-transform-delete' ? { _proof_version: 1, transform_id: 'transform', target: ['base', 'h', 0, 'FORWARD', 0] }
        : { _proof_version: 1, history_seed: '8ea7d453-6e52-4243-8d32-c6331dd134fd', ...residue() }
  packet.control_state.inputs = structuredClone(inputs); packet.control_context.inputs = structuredClone(inputs)
  if (kind === 'nucleotide-transform-delete') {
    const transform = { id: 'transform', ...residue(), copy_k: 0, crossover_id: null, extra_base_k: null }
    packet.before.display_topology.nucleotide_transforms.push(structuredClone(transform))
    packet.control_context.nucleotide_transforms.push(transform)
  }
  return packet
}
const linker = length_value => ({ id: 'link', name: null, overhang_a_id: 'a', overhang_a_attach: 'root',
  overhang_b_id: 'b', overhang_b_attach: 'free_end', linker_type: 'ss', length_value, length_unit: 'bp',
  bridge_relaxed: false, bridge_bin_index: 0, bridge_r_ee_min_nm: null, bridge_r_ee_max_nm: null,
  bridge_sequence: null, target_joint_id: null, unbound_angle_deg: null, bound_angle_deg: null })

describe('closed native transform display', () => {
  it('reuses only immutable JSON accounting and still validates new coordinates', () => {
    const c = compactTransformComponent()
    c.nucleotides.rows = Object.freeze(c.nucleotides.rows.map(row => Object.freeze([...row])))
    validateTransformPreviewComponent(c)
    c.nucleotides.f64 = ''
    expect(() => validateTransformPreviewComponent(c)).toThrow(/compact native DNA transport/)
  })
  it('charges cached frozen occurrences and their depth, including repeated aliases', () => {
    const probe = Object.freeze(['x'.repeat(10_000)]), c = transformComponent()
    c.probe = probe
    expect(() => validateTransformPreviewComponent(c)).toThrow(/fields/)
    c.probe = Array(201).fill(probe)
    expect(() => validateTransformPreviewComponent(c)).toThrow(/allowance/)
    c.probe = probe
    for (let i = 0; i < 64; i++) c.probe = [c.probe]
    expect(() => validateTransformPreviewComponent(c)).toThrow(/allowance/)
  })
  it('never caches a frozen container with mutable descendants', () => {
    const child = { value: 1 }, c = transformComponent()
    c.probe = Object.freeze([child])
    expect(() => validateTransformPreviewComponent(c)).toThrow(/fields/)
    child.value = Infinity
    expect(() => validateTransformPreviewComponent(c)).toThrow(/nonfinite/)
  })
  it('does not retain a stale validation after a component has been adopted', () => {
    const packet = transformPacket({ prepare: false })
    packet.candidate = compactTransformComponent(packet.candidate)
    validateTransformPreviewDisplay(packet, { prepare: false })
    consumeValidatedTransformPreviewComponent(packet.candidate)
    packet.candidate.nucleotides.f64 = ''
    expect(() => consumeValidatedTransformPreviewComponent(packet.candidate)).toThrow(/compact native DNA transport/)
  })
  it('validates compact native poses without changing transport', () => {
    const component = compactTransformComponent(), original = structuredClone(component)
    expect(validateTransformPreviewComponent(component)).toBe(component)
    expect(component).toEqual(original)
  })
  it('refuses malformed compact coordinates and ownership', () => {
    const bad = compactTransformComponent()
    bad.nucleotides.rows[0][5] = 'missing-strand'
    expect(() => validateTransformPreviewComponent(bad)).toThrow(/record\/source mismatch/)
    const truncated = compactTransformComponent()
    truncated.nucleotides.f64 = truncated.nucleotides.f64.slice(4)
    expect(() => validateTransformPreviewComponent(truncated)).toThrow(/compact native DNA transport/)
  })
  it.each([true, false])('validates complete Prepare/Evaluate controls without copying (prepare=%s)', prepare => {
    const packet = transformPacket({ prepare, envelope: true }), original = JSON.stringify(packet)
    expect(validateTransformPreviewDisplay(packet, { prepare, requireEnvelope: true })).toBe(packet)
    expect(JSON.stringify(packet)).toBe(original)
  })
  it('retains controls when visual geometry is off', () => {
    const packet = transformPacket({ prepare: false, geometry: false })
    expect(validateTransformPreviewDisplay(packet, { prepare: false })).toBe(packet)
    delete packet.control_state.placement_constraints
    expect(() => validateTransformPreviewDisplay(packet, { prepare: false })).toThrow()
  })
  it.each(['placement-poses', 'nucleotide-transform', 'nucleotide-transform-batch', 'nucleotide-transform-delete'])('accepts native %s controls', kind => {
    const packet = rolePacket(kind), before = JSON.stringify(packet)
    expect(validateTransformPreviewDisplay(packet, { prepare: true })).toBe(packet)
    expect(JSON.stringify(packet)).toBe(before)
  })
  it('retains the original lease role across the explicit complete-pose upgrade', () => {
    const packet = rolePacket('placement-poses'); packet.command_kind = 'cluster_op'
    packet.control_context.placement_upgrade = { upgrade_to: 'placement-poses-v1', expected_definition_sha256: 'a'.repeat(64) }
    expect(validateTransformPreviewDisplay(packet, { prepare: true })).toBe(packet)
    delete packet.control_context.placement_upgrade.expected_definition_sha256
    expect(() => validateTransformPreviewDisplay(packet, { prepare: true })).toThrow()
  })
  it.each([
    ['unselected primary', p => { p.control_state.inputs.primary_cluster_id = 'absent' }],
    ['duplicate selected owner', p => { p.control_state.inputs.selected_cluster_ids.push('placement') }],
    ['missing complete pose', p => { p.control_state.inputs.poses = [] }],
    ['foreign frame', p => { p.control_state.inputs.poses[0].parent_cluster_id = 'foreign' }],
    ['zero quaternion', p => { p.control_state.inputs.poses[0].rotation = [0, 0, 0, 0] }],
    ['fixed and moved owner', p => { p.control_state.inputs.authoring.fixed_cluster_ids = ['placement'] }],
    ['unowned joint', p => { p.control_state.inputs.authoring.joint_id = 'joint' }],
    ['unowned duplex pivot', p => { p.control_state.inputs.authoring.pivot_id = 'dup:taut'; p.control_state.inputs.authoring.mode = 'tethers' }],
    ['invented upgrade', p => { p.control_context.placement_upgrade = { upgrade_to: 'placement-poses-v1', expected_definition_sha256: 'a'.repeat(64) } }],
    ['reverse role transition', p => { p.evaluated_command_kind = 'cluster_op' }],
  ])('refuses complete-pose %s', (_name, damage) => {
    const packet = rolePacket('placement-poses'); damage(packet)
    expect(() => validateTransformPreviewDisplay(packet, { prepare: true })).toThrow()
  })
  it.each([
    ['missing target', p => { delete p.control_state.inputs.helix_id }],
    ['mixed namespace', p => { p.control_state.inputs.crossover_id = 'junction' }],
    ['absent copy', p => { p.control_state.inputs.copy_k = 5 }],
    ['wrong direction', p => { p.control_state.inputs.direction = 'REVERSE' }],
  ])('refuses native residue %s', (_name, damage) => {
    const packet = rolePacket('nucleotide-transform'); damage(packet)
    expect(() => validateTransformPreviewDisplay(packet, { prepare: true })).toThrow()
  })
  it('rejects duplicate batch targets and malformed or substituted reset identities', () => {
    const batch = rolePacket('nucleotide-transform-batch'); batch.control_state.inputs.transforms.push(residue())
    expect(() => validateTransformPreviewDisplay(batch, { prepare: true })).toThrow()
    const reset = rolePacket('nucleotide-transform-delete'); reset.control_state.inputs.target = ['base']
    expect(() => validateTransformPreviewDisplay(reset, { prepare: true })).toThrow()
    const wrong = rolePacket('nucleotide-transform-delete'); wrong.control_context.inputs.target[2] = 1
    expect(() => validateTransformPreviewDisplay(wrong, { prepare: true })).toThrow()
  })
  it.each([1e308, 4097, -1])('bounds finite scalar linker length %s before companion allocation', length => {
    const c = transformComponent(); c.display_topology.overhang_connections.push(linker(length)); c.required_renderers.push('ss-linker-arcs')
    expect(() => validateTransformPreviewComponent(c)).toThrow(/linker work allowance/)
  })
  it('bounds cumulative inserted-base allocation, not just each junction', () => {
    const c = transformComponent()
    c.display_topology.crossovers = Array.from({ length: 5 }, (_, i) => ({ id: `extra-${i}`,
      half_a: { helix_id: 'h', index: 0, strand: 'FORWARD' }, half_b: { helix_id: 'h', index: 1, strand: 'FORWARD' },
      extra_bases: 'A'.repeat(1024), process_id: null }))
    c.required_renderers.push('extra-bases')
    expect(() => validateTransformPreviewComponent(c)).toThrow(/render work allowance/)
  })
  it('charges native nm conversion and aggregate flexible companion records before allocation', () => {
    const c = transformComponent(); c.display_topology.overhang_connections.push({ ...linker(1500), length_unit: 'nm' })
    c.required_renderers.push('ss-linker-arcs')
    expect(() => validateTransformPreviewComponent(c)).toThrow(/linker work allowance/)
    const flexible = transformComponent(), anchor = { strand_id: 's', domain_index: 0, bp_index: 0, direction: 'FORWARD' }
    flexible.display_topology.flexible_connections = Array.from({ length: 5 }, (_, i) => ({ id: `flex-${i}`,
      cluster_a_id: 'placement', cluster_b_id: 'placement', anchor_a: anchor, anchor_b: anchor,
      n_ss_bases: 1024, contour_length_nm: 100, segment_bead_keys: Array(1024).fill(anchor) }))
    flexible.required_renderers.push('flexible-arcs')
    expect(() => validateTransformPreviewComponent(flexible)).toThrow(/render work allowance/)
  })
  it('bounds repeated axis-domain work even when every reference resolves', () => {
    const c = transformComponent(), segment = c.helix_axes[0].segments[0]
    c.helix_axes[0].segments = Array.from({ length: 5 }, () => ({ ...structuredClone(segment),
      domain_ids: Array.from({ length: 512 }, () => ({ strand_id: 's', domain_index: 0 })) }))
    expect(() => validateTransformPreviewComponent(c)).toThrow(/axis domain work allowance/)
  })
  it.each([
    ['wrong version', p => { p.projection_version = 2 }],
    ['proof claim', p => { p.source_equivalence_checked = true }],
    ['suffix claim', p => { p.downstream_evaluated = true }],
    ['wrong family', p => { p.family = 'deformation' }],
    ['invented identity', p => { p.deformation_id = 'placement' }],
    ['missing controls', p => { delete p.control_state }],
    ['missing first candidate', p => { p.candidate = null }],
    ['wrong frame claim', p => { p.control_state.frame_provenance.placement_poses.placement.frame = 'world' }],
    ['ambiguous owner', p => { p.control_state.cluster_transforms.push(p.control_state.cluster_transforms[0]) }],
    ['missing owner', p => { p.control_state.cluster_transforms[0].parent_cluster_id = 'absent' }],
    ['nonfinite control', p => { p.control_state.inputs.rotation[0] = Infinity }],
    ['unknown control', p => { p.control_state.live_design = {} }],
  ])('refuses %s', (_name, damage) => {
    const packet = transformPacket(); damage(packet)
    expect(() => validateTransformPreviewDisplay(packet, { prepare: true })).toThrow()
  })
  it('requires the closed host envelope when requested', () => {
    expect(() => validateTransformPreviewDisplay(transformPacket(), { prepare: true, requireEnvelope: true })).toThrow()
    const packet = transformPacket({ envelope: true }); delete packet.lease_id
    expect(() => validateTransformPreviewDisplay(packet, { prepare: true })).toThrow()
  })
  it.each([
    ['missing occupied record', c => c.nucleotides.pop()],
    ['duplicate record', c => c.nucleotides.push(c.nucleotides[0])],
    ['unknown record field', c => { c.nucleotides[0].atoms = [] }],
    ['null rigid slab', c => { c.nucleotides[0].slab_position = null }],
    ['bad native point', c => { c.nucleotides[0].backbone_position[0] = NaN }],
    ['wrong domain owner', c => { c.nucleotides[0].domain_index = 1 }],
    ['missing axes', c => { c.helix_axes = [] }],
    ['invented companion', c => { c.required_renderers = ['atoms'] }],
    ['unneeded companion', c => { c.required_renderers = ['extra-bases'] }],
    ['missing topology', c => { delete c.display_topology.extensions }],
    ['raw history', c => { c.display_topology.feature_log = [] }],
    ['unbounded domain', c => { c.display_topology.strands[0].domains[0].end_bp = 1e9 }],
  ])('refuses component %s before render allocation', (_name, damage) => {
    const component = transformComponent(); damage(component)
    expect(() => validateTransformPreviewComponent(component)).toThrow()
  })
  it('refuses cycles, non-JSON prototypes and over-budget strings without serializing them', () => {
    const cyclic = transformPacket(); cyclic.control_state.bad = cyclic
    expect(() => validateTransformPreviewDisplay(cyclic, { prepare: true })).toThrow()
    const accessor = transformPacket()
    Object.defineProperty(accessor.control_state, 'inputs', { enumerable: true, get() { throw new Error('accessor executed') } })
    expect(() => validateTransformPreviewDisplay(accessor, { prepare: true })).toThrow(/accessor/)
    const packet = transformPacket(); packet.control_context.strands[0].notes = 'x'.repeat(2_000_001)
    expect(() => validateTransformPreviewDisplay(packet, { prepare: true })).toThrow()
    const component = transformComponent(); Object.setPrototypeOf(component.nucleotides[0], { injected: true })
    expect(() => validateTransformPreviewComponent(component)).toThrow()
  })
})
