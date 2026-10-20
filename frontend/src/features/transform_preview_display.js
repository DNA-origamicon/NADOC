/** Closed native transform display. Validation returns the received object;
 * native rendering receives its own copy only after the entire packet passes. */
import { finite, integer, text, shape, vector, list } from './part_comparison_validation.js'
import { parseBaseKey } from '../scene/base_ref.js'
import { linkerLengthToBases } from '../scene/overhang_link_arcs.js'
import { visitDnaComparisonScalars, SCALAR_COLUMNS } from './part_dna_comparison_codec.js'
import { TRANSFORM_DISPLAY_LIMITS as limits } from './transform_preview_limits.js'

const fail = message => { throw new Error(`Transform preview unavailable: ${message}`) }
const id = v => text(v, 512), str = v => text(v, 2_000_000, true)
const num = v => { if (!finite(v)) fail('nonfinite number') }
const int = v => { if (!Number.isSafeInteger(v)) fail('invalid integer') }
const uint = v => { if (!integer(v)) fail('invalid nonnegative integer') }
const bool = v => { if (typeof v !== 'boolean') fail('invalid boolean') }
const literal = (...values) => v => { if (!values.includes(v)) fail('unsupported enum value') }
const nullable = check => v => { if (v !== null) check(v) }
const array = (check, maximum = 512) => v => { list(v, maximum); for (const item of v) check(item) }
const object = fields => {
  const keys = Object.keys(fields), entries = Object.entries(fields)
  return v => { shape(v, keys); for (const [key, check] of entries) check(v[key]) }
}
const optional = (v, required, extra = {}) => {
  shape(v, [...Object.keys(required), ...Object.keys(extra).filter(k => !Object.hasOwn(required, k) && Object.hasOwn(v ?? {}, k))])
  for (const [key, check] of Object.entries(required)) check(v[key])
  for (const [key, check] of Object.entries(extra)) if (Object.hasOwn(v, key)) check(v[key])
}
const map = check => v => { if (!v || Object.getPrototypeOf(v) !== Object.prototype) fail('invalid keyed object'); for (const [key, value] of Object.entries(v)) { id(key); check(value) } }
const vec = n => v => vector(v, n), xyz = object({ x: num, y: num, z: num })
const dir = literal('FORWARD', 'REVERSE'), nid = nullable(id), nstr = nullable(str), nnum = nullable(num)
const pose = { translation: vec(3), rotation: vec(4), pivot: vec(3) }
const ref = object({ strand_id: id, domain_index: uint })
const anchor = object({ strand_id: id, domain_index: uint, bp_index: int, direction: dir })
const end = object({ helix_id: id, bp: int, direction: dir })
const domain = object({ helix_id: id, start_bp: int, end_bp: int, direction: dir, overhang_id: nid, binds_overhang_id: nid })
const half = object({ helix_id: id, index: int, strand: dir })
const range = object({ helix_id: id, start_bp: int, end_bp: int, direction: dir, strand_id: nid, domain_index: nullable(uint) })
const json = () => {} // Only explicit native Any fields, already charged by boundedJson.
const groupFields = { id, name: str, is_default: bool, helix_ids: array(id), domain_ids: array(ref), color: nstr, opacity: num, auto_created: bool }
const placementFields = { ...groupFields, ...pose, parent_cluster_id: nid, overhang_duplex_driver_id: nid }
const helix = object({ id, axis_start: xyz, axis_end: xyz, native_residues: array(json, 0), native_source: literal(null),
  phase_offset: num, twist_per_bp_rad: num, length_bp: uint, bp_start: int,
  loop_skips: array(object({ bp_index: int, delta: literal(-1, 1) }), 1024), label: nstr,
  lattice_frame_id: nid, grid_pos: nullable(vec(2)), direction: nullable(dir) })
const strand = object({ id, domains: array(domain, 256), strand_type: literal('scaffold', 'staple', 'linker', 'oh_binder'),
  sequence: nstr, custom_scaffold_length: nullable(int), color: nstr, name: nstr, notes: nstr, is_reference: bool })
const subdomain = object({ id, name: str, color: nstr, start_bp_offset: int, length_bp: int, sequence_override: nstr,
  rotation_theta_deg: num, rotation_phi_deg: num, notes: str, tm_celsius: nnum, gc_percent: nnum, hairpin_warning: bool, dimer_warning: bool })
const jointFields = { id, cluster_id: id, name: str, joint_type: literal('revolute'), local_axis_origin: vec(3),
  local_axis_direction: vec(3), surface_detail: int, min_angle_deg: num, max_angle_deg: num }
const transformFields = { id, kind: literal('base', 'extra_base'), helix_id: nid, bp_index: nullable(int), direction: nullable(dir),
  copy_k: uint, crossover_id: nid, extra_base_k: nullable(uint), ...pose }
const joinEnd = object({ helix_id: id, bp_index: int, direction: dir })
const joinAttachment = object({ cluster_id: id, source: joinEnd, target: joinEnd })
const duplexEnd = object({ overhang_id: id, start_bp: int, end_bp: int })
const cpdFields = { id, base_key_1: id, base_key_2: id, product: literal('TT-CPD'),
  stereochemistry: literal('cis-syn', 'cis-syn-II', 'trans-syn-I', 'trans-syn-II', 'cis-anti-I', 'cis-anti-II', 'trans-anti-I', 'trans-anti-II') }
const organization = nullable(object({ version: literal(1), groups: array(object(groupFields)) }))
function deformation(v) {
  object({ id, type: literal('bend', 'twist', 'sweep'), targets: nullable(array(json)), target_ranges: nullable(array(range)),
    plane_a_bp: int, plane_b_bp: int, affected_helix_ids: array(id), cluster_ids: array(id), params: json })(v)
  if (v.targets !== null) for (const target of v.targets) {
    if (target?.kind === 'domain') {
      const camel = Object.hasOwn(target, 'strandId') || Object.hasOwn(target, 'domainIndex')
      object(camel ? { kind: literal('domain'), strandId: id, domainIndex: uint }
        : { kind: literal('domain'), strand_id: id, domain_index: uint })(target)
    } else object({ kind: literal('strand', 'cluster', 'part_group'), id })(target)
  }
  if (v.type === 'bend') {
    optional(v.params, { kind: literal('bend'), curvature_deg_per_bp: num, direction_deg: num },
      { endpoints: array(vec(3), 2), midpoint: vec(3), polymer_circle_count: uint })
    return
  }
  const fields = v.type === 'twist' ? { kind: literal('twist'), total_degrees: nnum, degrees_per_nm: nnum }
    : { kind: literal('sweep'), points_nm: array(vec(3), 256), origin_nm: vec(3), initial_rotation: vec(9),
        initial_tangent: nullable(vec(3)), point_frames: nullable(array(nullable(vec(9)), 256)), warning_bps: array(int, 2048),
        auto_loop_skips: bool, loop_skip_warnings: array(str, 2048), preceding_op_ids: array(id), direction: literal(-1, 1),
        start_step: int, steps: uint, path_length_nm: num, bp_positions_nm: nullable(array(vec(3), 2048)), bp_frames: nullable(array(vec(9), 2048)) }
  object(fields)(v.params)
}
const schemas = {
  lattice_frames: object({ id, plane: literal('XY', 'XZ', 'YZ'), placement_cluster_id: id }), helices: helix, strands: strand,
  cluster_transforms: object(placementFields), deformations: deformation, nucleotide_transforms: object(transformFields),
  cluster_joints: object(jointFields), cluster_join_constraints: object({ id, first: joinAttachment, second: joinAttachment, reach_nm: num }),
  overhangs: object({ id, helix_id: id, strand_id: id, sequence: nstr, label: nstr, ...pose, sub_domains: array(subdomain),
    parent_overhang_id: nid, auxiliary_endpoint: bool, strand_anim_setup: nullable(json) }),
  overhang_connections: object({ id, name: nstr, overhang_a_id: id, overhang_a_attach: literal('root', 'free_end'),
    overhang_b_id: id, overhang_b_attach: literal('root', 'free_end'), linker_type: literal('ss', 'ds'), length_value: num,
    length_unit: literal('bp', 'nm'), bridge_relaxed: bool, bridge_bin_index: int, bridge_r_ee_min_nm: nnum, bridge_r_ee_max_nm: nnum,
    bridge_sequence: nstr, target_joint_id: nid, unbound_angle_deg: nnum, bound_angle_deg: nnum }),
  overhang_bindings: object({ id, name: str, created_at: num, sub_domain_a_id: id, sub_domain_b_id: id,
    overhang_a_id: id, overhang_b_id: id, bound: bool, binding_mode: literal('duplex', 'toehold'), target_joint_id: nid,
    locked_angle_deg: nnum, prior_min_angle_deg: nnum, prior_max_angle_deg: nnum, allow_n_wildcard: bool,
    unbound_angle_deg: nnum, bound_angle_deg: nnum, driver_oh_id: nid, driven_oh_id: nid, connection_type: nstr }),
  connection_versions: object({ id, name: str, created_at: num, overhang_a_id: id, overhang_b_id: id, connection_type: str,
    overhang_a_seq: nstr, overhang_b_seq: nstr, bridge_length: int, bridge_seq: nstr, applied: bool }),
  duplexes: object({ id, name: str, created_at: num, left: duplexEnd, right: duplexEnd, driver: literal('left', 'right'),
    bound: bool, binding_mode: literal('duplex', 'toehold'), allow_n_wildcard: bool, target_joint_id: nid, locked_angle_deg: nnum, connection_type: nstr }),
  flexible_segment_marks: v => object({ id, strand_id: id, domain_index: uint, bp_index: int, direction: dir })(v),
  flexible_connections: object({ id, cluster_a_id: id, cluster_b_id: id, anchor_a: anchor, anchor_b: anchor,
    n_ss_bases: uint, contour_length_nm: num, segment_bead_keys: array(anchor, 1024) }),
  extensions: object({ id, strand_id: id, end: literal('five_prime', 'three_prime'), sequence: nstr, modification: nstr, label: nstr }),
  staple_groups: object({ id, name: str, color: nstr, strand_ids: array(id) }),
  photoproduct_junctions: object({ ...cpdFields, formation: literal('manual', 'legacy-scadnano'), patch_order: literal('base-key-1-first', 'base-key-2-first'),
    orientation_method: str, design_coordinates: map(map(vec(3))), t1_stable_id: nid, t2_stable_id: nid, photoproduct_id: str,
    representation_geometry: map(object({ backbone_position: vec(3), base_position: vec(3), frame_rotation: vec(4) })) }),
  crossovers: object({ id, half_a: half, half_b: half, extra_bases: nstr, process_id: nid }),
  crossover_constraints: object({ id, helix_ids_a: array(id), helix_ids_b: array(id), allowed_bp_intervals: array(vec(2)) }),
  forced_ligations: object({ id, three_prime_helix_id: id, three_prime_bp: int, three_prime_direction: dir,
    five_prime_helix_id: id, five_prime_bp: int, five_prime_direction: dir, extra_bases: nstr, is_periodic_seam: bool }),
}
const CONTROL_KEYS = ['lattice_frames', 'helices', 'strands', 'cluster_transforms', 'cluster_joints', 'cluster_join_constraints',
  'flexible_segment_marks', 'flexible_connections', 'crossovers', 'forced_ligations', 'extensions', 'nucleotide_transforms', 'photoproduct_junctions']
const KINDS = ['cluster_op', 'placement-poses', 'nucleotide-transform', 'nucleotide-transform-batch', 'nucleotide-transform-delete']
const ENVELOPE = ['preview_id', 'expected_design_id', 'expected_revision', 'lease_id', 'doc_id', 'request_sequence', 'remaining_seconds']
const key = (hid, bp, direction, copy = 0) => JSON.stringify([hid, bp, direction, copy])
const domainKey = (sid, ordinal) => JSON.stringify([sid, ordinal])

/** Bound occurrences, depth and encoded JSON bytes before any domain expansion.
 * Plain data only: no getters, prototypes, cycles or sparse-array coercion. */
const immutableJsonBounds = new WeakMap()
function boundedJson(value) {
  let nodes = 0, bytes = 0
  const active = new Set()
  function stringSize(value) {
    // Large compact coordinate blocks are ASCII without JSON escapes. Check
    // that property in the native regexp engine, then charge the exact bytes;
    // arbitrary Unicode/escaped strings keep the complete character walk.
    if (value.length >= 4096 && /^[\x20-\x21\x23-\x5b\x5d-\x7e]*$/.test(value)) {
      if (value.length + 2 > limits.bytes) fail('packet byte allowance exceeded')
      return value.length + 2
    }
    let size = 2
    for (const char of value) {
      const code = char.codePointAt(0)
      size += code < 32 ? ([8, 9, 10, 12, 13].includes(code) ? 2 : 6)
        : code === 34 || code === 92 ? 2 : code < 128 ? 1 : code < 2048 ? 2 : code <= 65535 ? (code >= 0xd800 && code <= 0xdfff ? 6 : 3) : 4
      if (size > limits.bytes) fail('packet byte allowance exceeded')
    }
    return size
  }
  function visit(v, depth) {
    const cached = v && typeof v === 'object' && immutableJsonBounds.get(v)
    if (cached) {
      nodes += cached.nodes; bytes += cached.bytes
      if (nodes > limits.nodes || bytes > limits.bytes || depth + cached.height > 64) fail('packet allowance exceeded')
      return cached.height
    }
    const initialNodes = nodes, initialBytes = bytes
    let height = 0, immutable = true
    if (++nodes > limits.nodes || depth > 64 || bytes > limits.bytes) fail('packet allowance exceeded')
    if (v === null) bytes += 4
    else if (typeof v === 'boolean') bytes += v ? 4 : 5
    else if (typeof v === 'number') { num(v); bytes += String(v).length }
    else if (typeof v === 'string') bytes += stringSize(v)
    else {
      if (!v || typeof v !== 'object' || active.has(v)) fail('non-JSON or cyclic packet')
      const isArray = Array.isArray(v)
      if (!isArray && Object.getPrototypeOf(v) !== Object.prototype) fail('non-JSON prototype')
      if (isArray && v.length > limits.nodes - nodes) fail('packet node allowance exceeded')
      const keys = Object.keys(v)
      if (keys.length > limits.nodes - nodes) fail('packet node allowance exceeded')
      const descriptors = Object.getOwnPropertyDescriptors(v)
      if (isArray && (keys.length !== v.length || keys.some((k, i) => k !== String(i)))) fail('sparse or extended array')
      if (Reflect.ownKeys(v).length !== keys.length + (isArray ? 1 : 0)) fail('hidden packet fields')
      active.add(v); bytes += 2 + Math.max(0, keys.length - 1)
      for (const k of keys) {
        if (!Object.hasOwn(descriptors[k], 'value')) fail('packet accessor')
        if (!isArray) bytes += stringSize(k) + 1
        const childHeight = visit(descriptors[k].value, depth + 1)
        if (childHeight === null) immutable = false
        else height = Math.max(height, childHeight + 1)
      }
      active.delete(v)
      immutable &&= Object.isFrozen(v)
      if (immutable) immutableJsonBounds.set(v, { nodes: nodes - initialNodes, bytes: bytes - initialBytes, height })
    }
    if (bytes > limits.bytes) fail('packet byte allowance exceeded')
    return immutable ? height : null
  }
  visit(value, 0)
}
function index(rows) {
  const result = new Map()
  for (const row of rows) { id(row.id); if (result.has(row.id)) fail('ambiguous identity'); result.set(row.id, row) }
  return result
}
function requireRef(values, value) { if (!values.has(value)) fail(`unresolved display reference: ${value}`) }
function member(ref, strands) { const d = strands.get(ref.strand_id)?.domains[ref.domain_index]; if (!d) fail('unresolved domain'); return d }
function equal(a, b) {
  if (a === b) return
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') fail('control geometry mismatch')
  if (Array.isArray(a) !== Array.isArray(b)) fail('control geometry mismatch')
  const keys = Object.keys(a); if (keys.length !== Object.keys(b).length) fail('control geometry mismatch')
  for (const k of keys) { if (!Object.hasOwn(b, k)) fail('control geometry mismatch'); equal(a[k], b[k]) }
}
function inventories(value, controls = false, liveControls = false) {
  const keys = controls ? CONTROL_KEYS : Object.keys(schemas)
  const out = {}
  for (const field of keys) {
    const check = controls && field === 'photoproduct_junctions' ? object(cpdFields)
      : liveControls && field === 'cluster_joints' ? object({ ...jointFields, axis_origin: vec(3), axis_direction: vec(3) }) : schemas[field]
    array(check, field === 'helices' ? limits.helices : field === 'strands' ? limits.strands : field === 'cluster_transforms' ? limits.owners : limits.selectors)(value[field])
    out[field] = index(value[field])
  }
  organization(value.group_organization)
  out.groups = index(value.group_organization?.groups ?? [])
  let domains = 0, spans = 0
  for (const s of value.strands) {
    domains += s.domains.length
    if (!s.domains.length || domains > limits.domains) fail('domain allowance exceeded')
    for (const d of s.domains) { requireRef(out.helices, d.helix_id); spans += Math.abs(d.end_bp - d.start_bp) + 1 }
  }
  if (spans > limits.nativeWork) fail('domain span allowance exceeded')
  for (const h of value.helices) {
    if (!h.length_bp || h.length_bp > 4096) fail('helix span allowance exceeded')
    if (h.lattice_frame_id !== null) requireRef(out.lattice_frames, h.lattice_frame_id)
  }
  for (const f of value.lattice_frames) requireRef(out.cluster_transforms, f.placement_cluster_id)
  for (const c of [...value.cluster_transforms, ...out.groups.values()]) {
    c.helix_ids.forEach(h => requireRef(out.helices, h)); c.domain_ids.forEach(r => member(r, out.strands))
    if (c.opacity < 0 || c.opacity > 1) fail('invalid group opacity')
  }
  for (const c of value.cluster_transforms) {
    const visited = new Set([c.id]); let parent = c.parent_cluster_id
    while (parent !== null) { requireRef(out.cluster_transforms, parent); if (visited.has(parent)) fail('cyclic placement'); visited.add(parent); parent = out.cluster_transforms.get(parent).parent_cluster_id }
  }
  for (const j of value.cluster_joints) requireRef(out.cluster_transforms, j.cluster_id)
  for (const x of value.extensions) requireRef(out.strands, x.strand_id)
  for (const c of value.flexible_connections) {
    requireRef(out.cluster_transforms, c.cluster_a_id); requireRef(out.cluster_transforms, c.cluster_b_id)
    if (c.n_ss_bases !== c.segment_bead_keys.length || c.n_ss_bases > 1024 || c.contour_length_nm < 0) fail('incomplete flexible segment')
    for (const a of [c.anchor_a, c.anchor_b, ...c.segment_bead_keys]) member(a, out.strands)
  }
  return out
}
const recordRequired = { helix_id: id, bp_index: int, direction: dir, backbone_position: vec(3), base_position: vec(3),
  base_normal: vec(3), axis_tangent: vec(3), placement_source: str, strand_id: id,
  strand_type: literal('scaffold', 'staple', 'linker', 'oh_binder'), is_five_prime: bool, is_three_prime: bool,
  domain_index: uint, overhang_id: nid }
const recordOptional = { copy_k: uint, helical_site: object({ axis_point: vec(3), radial_hat: vec(3), azimuth_rad: num, groove_offset_rad: num, phase_roll_rad: num }),
  is_reference: bool, is_flexible_segment: bool, is_unpaired: bool, slab_position: nullable(vec(3)), slab_quaternion: nullable(vec(4)),
  extension_id: id, nucleobase: nstr, is_modification: bool, modification: nstr }
const requiredRecordChecks = Object.entries(recordRequired), optionalRecordChecks = Object.entries(recordOptional)
const compactRecordChecks = SCALAR_COLUMNS.map(k => [k, recordRequired[k] ?? recordOptional[k]])
const recordKeys = new Set([...Object.keys(recordRequired), ...Object.keys(recordOptional)])
function checkRecord(n) {
  if (!n || Object.getPrototypeOf(n) !== Object.prototype || Object.keys(n).some(k => !recordKeys.has(k))
      || requiredRecordChecks.some(([k]) => !Object.hasOwn(n, k))) fail('incomplete or unsupported display fields')
  for (const [k, check] of requiredRecordChecks) check(n[k])
  for (const [k, check] of optionalRecordChecks) if (Object.hasOwn(n, k)) check(n[k])
}
function component(value) {
  shape(value, ['component_kind', 'component_version', 'representation', 'units', 'nucleotides', 'helix_axes', 'display_topology', 'required_renderers', 'bounds_nm'])
  if (value.component_kind !== 'transform-preview-dna' || ![1, 2].includes(value.component_version) || value.representation !== 'native-full-v1' || value.units !== 'nm') fail('unsupported component version')
  const compact = value.component_version === 2
  if (compact) {
    if (!value.nucleotides || Array.isArray(value.nucleotides) || value.nucleotides.count > limits.records) fail('invalid compact record inventory')
  } else list(value.nucleotides, limits.records)
  const recordCount = compact ? value.nucleotides.count : value.nucleotides.length
  const t = value.display_topology; shape(t, [...Object.keys(schemas), 'group_organization'])
  const indices = inventories(t), expected = new Map(), extensions = new Map(), changes = new Map()
  for (const h of t.helices) for (const mark of h.loop_skips) {
    if (mark.bp_index < h.bp_start || mark.bp_index >= h.bp_start + h.length_bp) fail('out-of-range loop/skip')
    const k = JSON.stringify([h.id, mark.bp_index]); changes.set(k, (changes.get(k) ?? 0) + mark.delta)
  }
  const occupied = new Set()
  for (const s of t.strands) s.domains.forEach((d, ordinal) => {
    for (let bp = Math.min(d.start_bp, d.end_bp); bp <= Math.max(d.start_bp, d.end_bp); bp++) {
      const address = key(d.helix_id, bp, d.direction)
      if (occupied.has(address)) fail('ambiguous directional occupancy'); occupied.add(address)
      if (d.helix_id.startsWith('__lnk__')) {
        const conn = indices.overhang_connections.get(d.helix_id.slice(7))
        if (!conn) fail('missing linker owner')
        if (conn.linker_type === 'ss') continue
      }
      const copies = Math.max(0, 1 + (changes.get(JSON.stringify([d.helix_id, bp])) ?? 0))
      if (copies + expected.size > limits.records) fail('record allowance exceeded')
      for (let copy = 0; copy < copies; copy++) expected.set(key(d.helix_id, bp, d.direction, copy), { s, d, ordinal })
    }
  })
  for (const e of t.extensions) {
    const s = indices.strands.get(e.strand_id), d = e.end === 'five_prime' ? s.domains[0] : s.domains.at(-1)
    const count = (e.sequence?.length ?? 0) + Number(!!e.modification)
    if (count + expected.size + extensions.size > limits.records) fail('extension allowance exceeded')
    for (let i = 0; i < count; i++) extensions.set(key(`__ext_${e.id}`, i, d.direction), e)
  }
  const seen = new Set(), bridgeBoundaries = new Set()
  let rigidCount = 0
  const visitRecord = (n, floats = null, offset = 0) => {
    if (floats) {
      for (const [k, check] of compactRecordChecks) check(n[k])
    } else checkRecord(n)
    if (!n.is_flexible_segment) rigidCount++
    if (n.helix_id.startsWith('__lnk__')) bridgeBoundaries.add(JSON.stringify([n.helix_id, n.strand_id, n.bp_index]))
    const k = key(n.helix_id, n.bp_index, n.direction, n.copy_k ?? 0), ext = extensions.get(k), owner = expected.get(k)
    if (seen.has(k)) fail('duplicate occupied record'); seen.add(k)
    if (ext) {
      if (n.extension_id !== ext.id || n.strand_id !== ext.strand_id || n.slab_position !== null || n.slab_quaternion !== null
          || !['native-full-extension-v1', 'chemical-modification-v1'].includes(n.placement_source)
          || n.is_modification !== (n.placement_source === 'chemical-modification-v1')
          || (n.is_modification && !n.modification)) fail('invalid slabless record')
    } else {
      if (!owner || n.strand_id !== owner.s.id || n.domain_index !== owner.ordinal || n.overhang_id !== owner.d.overhang_id
          || (n.is_reference ?? false) !== owner.s.is_reference || n.placement_source !== 'native-full-o5-v1') fail('record/source mismatch')
      if (floats) {
        // The codec validates all 28 doubles and fixes every vector/site shape.
        // Retain this validator's native quaternion/axis unit-length checks.
        if (Math.abs(Math.hypot(floats[offset + 15], floats[offset + 16], floats[offset + 17], floats[offset + 18]) - 1) > 1e-5
            || Math.abs(Math.hypot(floats[offset + 9], floats[offset + 10], floats[offset + 11]) - 1) > 1e-5) fail('invalid native frame')
      } else {
        recordOptional.helical_site(n.helical_site); vec(3)(n.slab_position); vec(4)(n.slab_quaternion)
        if (Math.abs(Math.hypot(...n.slab_quaternion) - 1) > 1e-5 || Math.abs(Math.hypot(...n.axis_tangent) - 1) > 1e-5) fail('invalid native frame')
      }
    }
  }
  if (compact) visitDnaComparisonScalars(value.nucleotides, visitRecord)
  else for (const n of value.nucleotides) visitRecord(n)
  renderWork(rigidCount, t)
  if (seen.size !== expected.size + extensions.size) fail('omitted occupied records')
  for (const c of t.overhang_connections) if (c.linker_type === 'ds' && linkerLengthToBases(c) > 0) {
    // The existing DS companion deliberately omits zero-length connector arcs.
    // Require its actual bridge endpoints rather than inventing replacement
    // arcs or accepting the native helper's initial-render anchor fallback.
    const hid = `__lnk__${c.id}`, count = linkerLengthToBases(c)
    for (const [side, bp] of [['a', 0], ['b', count - 1]])
      if (!bridgeBoundaries.has(JSON.stringify([hid, `${hid}__${side}`, bp]))) fail('missing native DS bridge boundary')
  }
  axes(value.helix_axes, t, indices)
  const required = []
  if ([...t.crossovers, ...t.forced_ligations].some(c => c.extra_bases?.length)) required.push('extra-bases')
  if (t.photoproduct_junctions.length) required.push('photoproducts')
  if (t.flexible_connections.length) required.push('flexible-arcs')
  if (t.overhang_connections.some(c => c.linker_type === 'ss')) required.push('ss-linker-arcs')
  equal(value.required_renderers, required)
  const junctions = new Map([...indices.crossovers, ...indices.forced_ligations])
  if (junctions.size !== t.crossovers.length + t.forced_ligations.length) fail('ambiguous junction namespace')
  for (const c of [...t.crossovers, ...t.forced_ligations]) {
    const endpoints = c.half_a ? [c.half_a, c.half_b] : ['three_prime', 'five_prime'].map(p => ({ helix_id: c[`${p}_helix_id`], index: c[`${p}_bp`], strand: c[`${p}_direction`] }))
    for (const e of endpoints) if (!expected.has(key(e.helix_id, e.index, e.strand))) fail('missing junction endpoint')
    if ((c.extra_bases?.length ?? 0) > 1024) fail('extra-base allowance exceeded')
  }
  for (const lesion of t.photoproduct_junctions) {
    const converted = Object.keys(lesion.design_coordinates)
    if (converted.length) {
      equal(converted.sort(), [lesion.base_key_1, lesion.base_key_2].sort())
      equal(Object.keys(lesion.representation_geometry).sort(), converted)
    } else if (Object.keys(lesion.representation_geometry).length) fail('unowned CPD geometry')
    for (const k of [lesion.base_key_1, lesion.base_key_2]) {
      const parsed = parseBaseKey(k)
      const valid = parsed?.crossover_id != null ? (junctions.get(parsed.crossover_id)?.extra_bases?.length ?? 0) > parsed.k
        : parsed && expected.has(key(parsed.helix_id, parsed.bp_index, parsed.direction, parsed.copy ?? 0))
      if (!valid) fail('missing photoproduct endpoint')
    }
  }
  if (value.bounds_nm !== null) {
    object({ minimum: vec(3), maximum: vec(3) })(value.bounds_nm)
    if (value.bounds_nm.minimum.some((v, i) => v > value.bounds_nm.maximum[i])) fail('invalid component bounds')
  } else if (recordCount || value.helix_axes.length) fail('missing component bounds')
  return indices
}

/** Native companion meshes expand scalar counts, independently of JSON size.
 * Charge the actual render families together before any Three allocation. The
 * conversion is the ordinary renderer's own helper, not a second physical rule. */
function renderWork(rigidCount, topology) {
  let work = rigidCount
  const charge = amount => {
    if (!Number.isSafeInteger(amount) || amount < 0 || (work += amount) > limits.nativeWork) fail('native render work allowance exceeded')
  }
  for (const c of topology.flexible_connections) charge(c.n_ss_bases)
  for (const c of [...topology.crossovers, ...topology.forced_ligations]) charge(c.extra_bases?.length ?? 0)
  for (const c of topology.overhang_connections) {
    if (c.length_value < 0 || c.length_value > 4096) fail('linker work allowance exceeded')
    const count = linkerLengthToBases(c)
    if (!Number.isSafeInteger(count) || count > 4096) fail('linker work allowance exceeded')
    // DS records are already charged above. The scalar still determines which
    // native boundary records the connector helper reads, so it remains bounded.
    if (c.linker_type === 'ss') charge(count)
  }
}
function axes(values, topology, indices) {
  list(values, limits.helices); const seen = new Set(), coverage = new Map(); let points = 0, domainVisits = 0
  const point = p => { vec(3)(p); if (++points > limits.axisPoints) fail('axis point allowance exceeded') }
  for (const axis of values) {
    optional(axis, { helix_id: id, start: point, end: point, samples: array(point, limits.axisPoints), segments: array(json, 512) }, { ovhg_axes: map(json) })
    if (!indices.helices.has(axis.helix_id) || axis.helix_id.startsWith('__lnk__') || seen.has(axis.helix_id)) fail('invalid axis identity')
    seen.add(axis.helix_id)
    for (const segment of axis.segments) {
      optional(segment, { strand_id: nid, domain_index: nullable(uint), ovhg_id: nid, bp_lo: int, bp_hi: int, start: point, end: point },
        { domain_ids: array(ref), samples: array(point, limits.axisPoints) })
      const refs = segment.domain_ids?.length ? segment.domain_ids : segment.strand_id === null ? [] : [{ strand_id: segment.strand_id, domain_index: segment.domain_index }]
      for (const r of refs) {
        const d = member(r, indices.strands)
        if (d.helix_id !== axis.helix_id || segment.bp_lo > segment.bp_hi || segment.bp_lo < Math.min(d.start_bp, d.end_bp)
            || segment.bp_hi > Math.max(d.start_bp, d.end_bp)) fail('axis/domain mismatch')
        domainVisits += segment.bp_hi - segment.bp_lo + 1
        if (domainVisits > limits.nativeWork) fail('axis domain work allowance exceeded')
        const k = domainKey(r.strand_id, r.domain_index); if (!coverage.has(k)) coverage.set(k, new Set())
        for (let bp = segment.bp_lo; bp <= segment.bp_hi; bp++) coverage.get(k).add(bp)
      }
    }
    for (const [oid, o] of Object.entries(axis.ovhg_axes ?? {})) {
      object({ bp_min: int, bp_max: int, start: point, end: point })(o)
      if (indices.overhangs.get(oid)?.helix_id !== axis.helix_id) fail('missing overhang axis owner')
    }
  }
  if (seen.size !== topology.helices.filter(h => !h.id.startsWith('__lnk__')).length) fail('missing helix axes')
  const flexible = new Map()
  for (const mark of topology.flexible_segment_marks) {
    const hid = member(mark, indices.strands).helix_id
    if (!flexible.has(hid)) flexible.set(hid, new Set()); flexible.get(hid).add(mark.bp_index)
  }
  for (const s of topology.strands) s.domains.forEach((d, ordinal) => {
    if (d.helix_id.startsWith('__lnk__')) return
    const covered = coverage.get(domainKey(s.id, ordinal)) ?? new Set(), omitted = flexible.get(d.helix_id)
    for (let bp = Math.min(d.start_bp, d.end_bp); bp <= Math.max(d.start_bp, d.end_bp); bp++)
      if (covered.has(bp) === !!omitted?.has(bp)) fail('incomplete rigid axis coverage')
  })
}

function nonzeroPose(v) {
  const norm = Math.hypot(...v.rotation)
  if (!Number.isFinite(norm) || norm < 1e-12) fail('invalid pose quaternion')
}
function uniqueIds(values, maximum = 32, nonempty = false) {
  array(id, maximum)(values)
  if ((nonempty && !values.length) || new Set(values).size !== values.length) fail('ambiguous selected owners')
}
function residueTarget(v) {
  if (v.kind === 'base') {
    id(v.helix_id); int(v.bp_index); dir(v.direction)
    if (v.crossover_id != null || v.extra_base_k != null) fail('mixed residue target namespaces')
    return ['base', v.helix_id, v.bp_index, v.direction, v.copy_k ?? 0]
  }
  id(v.crossover_id); uint(v.extra_base_k)
  if (v.helix_id != null || v.bp_index != null || v.direction != null) fail('mixed residue target namespaces')
  return ['extra_base', v.crossover_id, v.extra_base_k]
}
function resetTarget(v) {
  if (!Array.isArray(v)) fail('invalid reset target')
  if (v[0] === 'base' && v.length === 5) { id(v[1]); int(v[2]); dir(v[3]); uint(v[4]) }
  else if (v[0] === 'extra_base' && v.length === 3) { id(v[1]); uint(v[2]) }
  else fail('invalid reset target')
  return v
}
const authored = { name: v => text(v, 512, true), helix_ids: array(id), domain_ids: array(ref), color: nullable(v => text(v, 512, true)), opacity: num }
function input(v, kind, indices, live) {
  const protectedFields = { _proof_version: literal(1), history_seed: id, expected_design_id: id, expected_revision: uint, expected_feature_id: id }
  const body = { kind: literal('base', 'extra_base'), ...pose }
  const extra = { helix_id: nid, bp_index: nullable(int), direction: nullable(dir), copy_k: uint, crossover_id: nid, extra_base_k: nullable(uint), compose: bool }
  const membership = values => {
    for (const h of values.helix_ids ?? []) requireRef(indices.helices, h)
    for (const r of values.domain_ids ?? []) member(r, indices.strands)
  }
  if (kind === 'cluster_op') {
    optional(v, { _proof_version: literal(1), cluster_id: id, ...pose }, authored)
    nonzeroPose(v); requireRef(indices.cluster_transforms, v.cluster_id); membership(v)
    return
  }
  if (kind === 'placement-poses') {
    object({ _proof_version: literal(1), primary_cluster_id: id, selected_cluster_ids: array(id, 32),
      poses: array(object({ cluster_id: id, ...pose, parent_cluster_id: nid, overhang_duplex_driver_id: nid }), 32),
      authoring: object({ mode: literal('free', 'joint', 'tethers'), joint_id: nid, fixed_cluster_ids: array(id, 32), pivot_id: id }),
      primary_authored_fields: values => optional(values, {}, authored), legacy_source: nullable(v => text(v, 512, true)) })(v)
    uniqueIds(v.selected_cluster_ids, 32, true)
    const owners = v.poses.map(p => p.cluster_id); uniqueIds(owners, 32, true)
    if (!v.selected_cluster_ids.includes(v.primary_cluster_id) || v.selected_cluster_ids.some(i => !owners.includes(i))) fail('incomplete placement poses')
    for (const p of v.poses) {
      nonzeroPose(p); requireRef(indices.cluster_transforms, p.cluster_id)
      const owner = indices.cluster_transforms.get(p.cluster_id)
      if (p.parent_cluster_id !== owner.parent_cluster_id || p.overhang_duplex_driver_id !== owner.overhang_duplex_driver_id) fail('wrong placement frame')
    }
    membership(v.primary_authored_fields)
    const a = v.authoring; uniqueIds(a.fixed_cluster_ids)
    for (const fixed of a.fixed_cluster_ids) { requireRef(indices.cluster_transforms, fixed); if (owners.includes(fixed)) fail('fixed owner receives a pose') }
    if (a.mode === 'joint') {
      id(a.joint_id); requireRef(indices.cluster_joints, a.joint_id)
      if (a.pivot_id !== a.joint_id || indices.cluster_joints.get(a.joint_id).cluster_id !== v.primary_cluster_id) fail('wrong joint owner')
    } else if (a.joint_id !== null) fail('unowned joint control')
    if (a.mode === 'free' && a.pivot_id !== 'centroid' && !a.pivot_id.startsWith('dup:root:')) fail('unsupported free pivot')
    if (a.mode === 'tethers' && !['ssdna', 'dup:taut'].includes(a.pivot_id)) fail('unsupported tether pivot')
    if (a.pivot_id.startsWith('dup:root:') || a.pivot_id === 'dup:taut') {
      const owner = indices.cluster_transforms.get(v.primary_cluster_id)
      if (!owner.overhang_duplex_driver_id) fail('duplex pivot has no driver')
      if (a.pivot_id.startsWith('dup:root:')) id(a.pivot_id.slice(9))
    }
    return
  }
  let targets
  const checkedBody = b => { optional(b, body, extra); nonzeroPose(b); return residueTarget(b) }
  if (kind === 'nucleotide-transform-batch') {
    optional(v, { _proof_version: literal(1), history_seed: id, transforms: array(json, 1024) }, protectedFields)
    if (!v.transforms.length) fail('empty transform batch')
    targets = v.transforms.map(checkedBody)
    if (new Set(targets.map(t => JSON.stringify(t))).size !== targets.length) fail('duplicate residue target')
  } else if (kind === 'nucleotide-transform-delete') {
    optional(v, { _proof_version: literal(1), transform_id: id }, { ...protectedFields, target: resetTarget })
    if (!live) {
      requireRef(indices.nucleotide_transforms, v.transform_id)
      if (v.target) equal(v.target, residueTarget(indices.nucleotide_transforms.get(v.transform_id)))
    }
    targets = v.target ? [v.target] : []
  } else {
    optional(v, { _proof_version: literal(1), history_seed: id, ...body }, { ...extra, ...protectedFields })
    nonzeroPose(v); targets = [residueTarget(v)]
  }
  // Build a bounded directional site inventory once, including native loop
  // copies. A target is never rebound by proximity or a current strand ordinal.
  const available = new Set(), changes = new Map()
  for (const h of indices.helices.values()) for (const mark of h.loop_skips) {
    const k = JSON.stringify([h.id, mark.bp_index]); changes.set(k, (changes.get(k) ?? 0) + mark.delta)
  }
  for (const s of indices.strands.values()) for (const d of s.domains) {
    for (let bp = Math.min(d.start_bp, d.end_bp); bp <= Math.max(d.start_bp, d.end_bp); bp++) {
      const copies = Math.max(0, 1 + (changes.get(JSON.stringify([d.helix_id, bp])) ?? 0))
      if (available.size + copies > limits.nativeWork) fail('target site allowance exceeded')
      for (let copy = 0; copy < copies; copy++) available.add(JSON.stringify(['base', d.helix_id, bp, d.direction, copy]))
    }
  }
  for (const target of targets) {
    if (target[0] === 'base') { if (!available.has(JSON.stringify(target))) fail('unresolved residue target') }
    else {
      const junction = indices.crossovers.get(target[1]) ?? indices.forced_ligations.get(target[1])
      if (!junction || target[2] >= (junction.extra_bases?.length ?? 0)) fail('unresolved inserted-base target')
    }
  }
}
function controls(v, topology, kind, live) {
  shape(v, [...CONTROL_KEYS, 'group_organization', 'inputs', 'lattice_type', ...(live ? ['flexible_gates', 'placement_constraints', 'frame_provenance'] : ['placement_upgrade'])])
  literal('SQUARE', 'HONEYCOMB')(v.lattice_type)
  const indices = inventories(v, true, live)
  input(v.inputs, kind, indices, live)
  if (topology) for (const field of [...CONTROL_KEYS, 'group_organization']) {
    const counterpart = topology[field]
    if (field === 'photoproduct_junctions') {
      equal(v[field], counterpart.map(p => Object.fromEntries(Object.keys(cpdFields).map(k => [k, p[k]]))))
    } else if (field === 'cluster_joints' && live) {
      equal(v[field].map(j => Object.fromEntries(Object.keys(jointFields).map(k => [k, j[k]]))), counterpart)
    } else equal(v[field], counterpart)
  }
  if (!live) return
  map(g => object({ cluster_id: id, gate: bool, n_crossings: uint, rigid_blocking: array(object({ a: anchor, b: anchor }), 4096) })(g))(v.flexible_gates)
  equal(Object.keys(v.flexible_gates).sort(), [...indices.cluster_transforms.keys()].sort())
  for (const [key, gate] of Object.entries(v.flexible_gates)) if (key !== gate.cluster_id) fail('wrong flexible gate identity')
  const tether = t => optional(t, { moving: end, fixed: end, contour_nm: num }, { rigid: bool })
  const rotationPoint = object({ kind: literal('overhang_root', 'centroid'), overhang_id: nid, label: str, point: vec(3) })
  array(object({ cluster_id: id, rotation_points: array(rotationPoint), tethers: array(tether),
    movable_links: array(object({ kind: literal('duplex'), link_cluster_id: id, helix_ids: array(id), domain_ids: array(ref),
      tethers: array(object({ l: end, part: end, contour_nm: num, part_dragged: bool })) })) }), 32)(v.placement_constraints)
  equal(v.placement_constraints.map(c => c.cluster_id), v.cluster_transforms.map(c => c.id))
  object({ joint_axes: map(object({ method: literal('native-owner-transform'), owner_id: id, parent_cluster_id: nid, parent_composed: literal(false) })),
    rotation_points: map(object({ frame: literal('native-rest-with-placement-poses-removed') })),
    placement_poses: map(object({ parent_cluster_id: nid, frame: literal('parent-rest', 'native-design') })) })(v.frame_provenance)
  equal(Object.keys(v.frame_provenance.placement_poses).sort(), [...indices.cluster_transforms.keys()].sort())
  equal(Object.keys(v.frame_provenance.joint_axes).sort(), [...indices.cluster_joints.keys()].sort())
  for (const c of v.cluster_transforms) {
    const frame = v.frame_provenance.placement_poses[c.id]
    if (frame.parent_cluster_id !== c.parent_cluster_id || frame.frame !== (c.parent_cluster_id === null ? 'native-design' : 'parent-rest')) fail('wrong placement frame')
  }
}

export function validateTransformPreviewComponent(value) {
  checkedComponents.delete(value)
  boundedJson(value); component(value); return value
}

const checkedComponents = new WeakSet()
/** Consume the controller's completed validation once during synchronous
 * adoption. Standalone builders still validate their complete input. */
export function consumeValidatedTransformPreviewComponent(value) {
  return value && typeof value === 'object' && checkedComponents.delete(value)
    ? value : validateTransformPreviewComponent(value)
}

export function validateTransformPreviewDisplay(value, { prepare, requireEnvelope = false } = {}) {
  checkedComponents.delete(value?.before)
  checkedComponents.delete(value?.candidate)
  if (typeof prepare !== 'boolean' || typeof requireEnvelope !== 'boolean') fail('explicit display stage required')
  boundedJson(value)
  const envelope = ENVELOPE.some(k => Object.hasOwn(value ?? {}, k))
  if (requireEnvelope && !envelope) fail('missing host envelope')
  shape(value, ['projection_version', 'family', 'command_kind', 'evaluated_command_kind', 'feature_id', 'stage', 'source_equivalence_checked',
    'downstream_evaluated', 'physical_validity', 'control_state', 'candidate', ...(prepare ? ['before', 'control_context'] : []), ...(envelope ? ENVELOPE : [])])
  if (value.projection_version !== 1 || value.family !== 'transform' || !KINDS.includes(value.command_kind) || !KINDS.includes(value.evaluated_command_kind)
      || value.stage !== 'feature' || value.source_equivalence_checked !== false || value.downstream_evaluated !== false || value.physical_validity !== false) fail('unsupported display claim')
  if (value.command_kind !== value.evaluated_command_kind && (value.command_kind !== 'cluster_op' || value.evaluated_command_kind !== 'placement-poses')) fail('unsupported role transition')
  text(value.feature_id)
  if (envelope) {
    for (const k of ['preview_id', 'expected_design_id', 'lease_id']) text(value[k])
    text(value.doc_id, 1024); uint(value.expected_revision); uint(value.request_sequence); num(value.remaining_seconds)
    if (value.remaining_seconds < 0) fail('expired display lease')
  }
  if (prepare) component(value.before)
  if (value.candidate !== null) component(value.candidate)
  else if (prepare) fail('missing initial candidate')
  controls(value.control_state, value.candidate?.display_topology, value.evaluated_command_kind, true)
  if (prepare) {
    controls(value.control_context, value.before.display_topology, value.evaluated_command_kind, false)
    const upgrade = value.control_context.placement_upgrade
    if (value.command_kind === 'cluster_op') object({ upgrade_to: literal('placement-poses-v1'), expected_definition_sha256: v => {
      if (typeof v !== 'string' || !/^[0-9a-f]{64}$/.test(v)) fail('invalid original definition digest')
    } })(upgrade)
    else if (upgrade !== null) fail('unowned placement upgrade')
  }
  if (prepare) checkedComponents.add(value.before)
  if (value.candidate !== null) checkedComponents.add(value.candidate)
  return value
}
