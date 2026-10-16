/** Closed native DNA display component; never a Design or construction input. */
import { fail, finite, integer, text, shape, vector, list, unique } from './part_comparison_validation.js'
import { decodeDnaComparisonRecords } from './part_dna_comparison_codec.js'

const MAX_SITES = 1024, MAX_SELECTORS = 512
const directions = new Set(['FORWARD', 'REVERSE'])
const siteKey = n => JSON.stringify([n.helix_id, n.bp_index, n.direction, n.copy_k])
const ownerKey = (sid, index) => JSON.stringify([sid, index])
const bp = value => { if (!Number.isSafeInteger(value) || Math.abs(value) > 1e6) fail('invalid DNA bp address') }
const nullableId = value => { if (value !== null) text(value) }
const boolean = value => { if (typeof value !== 'boolean') fail('invalid DNA display flag') }
const sequence = value => { if (value !== null) text(value, 100000, true) }
const color = value => { if (value !== null && (typeof value !== 'string' || !/^#[\da-f]{6}$/i.test(value))) fail('invalid DNA display color') }
function direction(value) { if (!directions.has(value)) fail('invalid DNA direction') }
function pointObject(value) { shape(value, ['x', 'y', 'z']); vector([value.x, value.y, value.z], 3) }
function bounds(value, occupied) {
  if (value === null) { if (occupied) fail('missing DNA bounds'); return }
  shape(value, ['minimum', 'maximum']); vector(value.minimum, 3); vector(value.maximum, 3)
  if (value.minimum.some((x, i) => x > value.maximum[i])) fail('invalid DNA bounds')
}
function domainRef(value, strands) {
  shape(value, ['strand_id', 'domain_index']); text(value.strand_id)
  if (!integer(value.domain_index) || !strands.get(value.strand_id)?.domains[value.domain_index]) fail('unresolved DNA domain reference')
  return strands.get(value.strand_id).domains[value.domain_index]
}
function referenceIds(values, owners) {
  list(values, MAX_SELECTORS)
  for (const id of values) { text(id); if (!owners.has(id)) fail('unresolved DNA display reference') }
}

export function validateDnaComparisonComponent(value) {
  shape(value, ['component_version', 'representation', 'units', 'nucleotides', 'helix_axes', 'display_topology', 'bounds_nm'])
  if (value.component_version !== 2 || value.representation !== 'native-full-v1' || value.units !== 'nm') fail('unsupported DNA display version')
  return validateNativeComponent(value, false)
}

/** Separate closed wire contract; comparison v2 still refuses scoped samples. */
export function validateDeformationPreviewComponent(value) {
  shape(value, ['component_kind', 'component_version', 'representation', 'units', 'nucleotides', 'helix_axes', 'display_topology', 'bounds_nm'])
  if (value.component_kind !== 'deformation-preview-dna' || value.component_version !== 1
      || value.representation !== 'native-full-v1' || value.units !== 'nm') fail('unsupported deformation display version')
  return validateNativeComponent(value, true)
}

function validateNativeComponent(value, scopedSamples) {
  const topology = value.display_topology
  shape(topology, ['helices', 'strands', 'overhangs', 'cluster_transforms', 'deformations', 'crossovers', 'forced_ligations'])
  list(topology.helices, 16); list(topology.strands, 128)
  for (const key of ['overhangs', 'cluster_transforms', 'deformations', 'crossovers', 'forced_ligations']) list(topology[key], MAX_SELECTORS)
  if (topology.cluster_transforms.length + topology.deformations.length > 64) fail('DNA operation allowance exceeded')
  for (const items of Object.values(topology)) unique(items)
  const helices = new Map(topology.helices.map(h => [h.id, h]))
  const strands = new Map(topology.strands.map(s => [s.id, s]))
  const overhangs = new Map(topology.overhangs.map(o => [o.id, o]))
  const deltas = new Map(), extent = new Map(), domains = new Map(), expected = new Map()
  const occupied = new Set(), overhangOwners = new Map()
  let prospective = 0, walked = 0, domainCount = 0, selectors = 0
  for (const helix of topology.helices) {
    shape(helix, ['id', 'length_bp', 'bp_start', 'axis_start', 'axis_end', 'loop_skips', 'direction', 'grid_pos', 'lattice_frame_id'])
    bp(helix.bp_start)
    if (!integer(helix.length_bp) || helix.length_bp < 1 || helix.length_bp > MAX_SITES / 2) fail('DNA helix span allowance exceeded')
    if (/^__(lnk|np|strep_dna)__/.test(helix.id)) fail('unsupported DNA attachment helix')
    pointObject(helix.axis_start); pointObject(helix.axis_end)
    if (helix.direction !== null) direction(helix.direction)
    nullableId(helix.lattice_frame_id)
    if (helix.grid_pos !== null) { vector(helix.grid_pos, 2); if (!helix.grid_pos.every(Number.isSafeInteger)) fail('invalid lattice address') }
    list(helix.loop_skips, MAX_SITES)
    const changes = new Map()
    for (const change of helix.loop_skips) {
      shape(change, ['bp_index', 'delta']); bp(change.bp_index)
      if (![-1, 1].includes(change.delta) || change.bp_index < helix.bp_start || change.bp_index >= helix.bp_start + helix.length_bp) fail('invalid DNA loop/skip address')
      changes.set(change.bp_index, (changes.get(change.bp_index) ?? 0) + change.delta)
      prospective += 2 * Math.max(0, change.delta)
    }
    deltas.set(helix.id, changes)
    prospective += 2 * helix.length_bp
    if (prospective > MAX_SITES) fail('DNA prospective site allowance exceeded')
    extent.set(helix.id, [helix.bp_start, helix.bp_start + helix.length_bp - 1])
  }
  for (const strand of topology.strands) {
    shape(strand, ['id', 'domains', 'strand_type', 'sequence', 'color', 'is_reference'])
    if (!['scaffold', 'staple'].includes(strand.strand_type) || strand.id.startsWith('__lnk__')) fail('unsupported DNA strand')
    list(strand.domains, 256); domainCount += strand.domains.length
    if (!strand.domains.length || domainCount > 256) fail('DNA domain allowance exceeded')
    sequence(strand.sequence); color(strand.color); boolean(strand.is_reference)
    for (const [index, domain] of strand.domains.entries()) {
      shape(domain, ['helix_id', 'start_bp', 'end_bp', 'direction', 'overhang_id', 'binds_overhang_id'])
      text(domain.helix_id); direction(domain.direction); bp(domain.start_bp); bp(domain.end_bp)
      if (!helices.has(domain.helix_id) || domain.binds_overhang_id !== null) fail('unresolved or unsupported DNA domain')
      if (domain.overhang_id !== null && !overhangs.has(domain.overhang_id)) fail('unresolved overhang owner')
      const lo = Math.min(domain.start_bp, domain.end_bp), hi = Math.max(domain.start_bp, domain.end_bp)
      if ((domain.direction === 'FORWARD' && domain.start_bp > domain.end_bp) || (domain.direction === 'REVERSE' && domain.start_bp < domain.end_bp)) fail('invalid native domain traversal')
      walked += hi - lo + 1
      if (walked > MAX_SITES) fail('DNA domain walk allowance exceeded')
      domains.set(ownerKey(strand.id, index), domain)
      if (domain.overhang_id !== null) {
        if (overhangOwners.has(domain.overhang_id)) fail('ambiguous overhang ownership')
        overhangOwners.set(domain.overhang_id, { strandId: strand.id, helixId: domain.helix_id })
      }
      const range = extent.get(domain.helix_id); range[0] = Math.min(range[0], lo); range[1] = Math.max(range[1], hi)
      for (let address = lo; address <= hi; address++) {
        const addressKey = JSON.stringify([domain.helix_id, address, domain.direction])
        if (occupied.has(addressKey)) fail('ambiguous occupied DNA site')
        occupied.add(addressKey)
        for (let copy = 0; copy < Math.max(0, 1 + (deltas.get(domain.helix_id).get(address) ?? 0)); copy++) {
          const key = siteKey({ helix_id: domain.helix_id, bp_index: address, direction: domain.direction, copy_k: copy })
          expected.set(key, { strand, index, domain })
        }
      }
    }
  }
  for (const [id, range] of extent) {
    const h = helices.get(id)
    prospective += 2 * (h.bp_start - range[0] + range[1] - (h.bp_start + h.length_bp - 1))
  }
  if (prospective > MAX_SITES || expected.size > MAX_SITES) fail('DNA prospective site allowance exceeded')
  const subdomains = new Set()
  for (const overhang of topology.overhangs) {
    shape(overhang, ['id', 'helix_id', 'strand_id', 'sequence', 'sub_domains']); sequence(overhang.sequence)
    const owner = overhangOwners.get(overhang.id)
    if (owner?.strandId !== overhang.strand_id || owner?.helixId !== overhang.helix_id) fail('ambiguous overhang ownership')
    list(overhang.sub_domains, MAX_SELECTORS); selectors += overhang.sub_domains.length
    for (const sub of overhang.sub_domains) {
      shape(sub, ['id', 'start_bp_offset', 'length_bp', 'sequence_override', 'color']); text(sub.id)
      if (subdomains.has(sub.id)) fail('ambiguous overhang subdomain')
      subdomains.add(sub.id); bp(sub.start_bp_offset); bp(sub.length_bp); sequence(sub.sequence_override); color(sub.color)
    }
  }
  for (const cluster of topology.cluster_transforms) {
    shape(cluster, ['id', 'name', 'is_default', 'helix_ids', 'domain_ids', 'color', 'auto_created'])
    text(cluster.name, 4096, true); boolean(cluster.is_default); boolean(cluster.auto_created); color(cluster.color)
    referenceIds(cluster.helix_ids, helices); list(cluster.domain_ids, MAX_SELECTORS)
    selectors += cluster.helix_ids.length + cluster.domain_ids.length
    for (const ref of cluster.domain_ids) domainRef(ref, strands)
  }
  for (const op of topology.deformations) {
    shape(op, ['id', 'type', 'affected_helix_ids', 'target_ranges', 'plane_a_bp', 'plane_b_bp', 'params'])
    if (!['bend', 'twist', 'sweep'].includes(op.type)) fail('unsupported DNA display provenance')
    referenceIds(op.affected_helix_ids, helices); bp(op.plane_a_bp); bp(op.plane_b_bp)
    selectors += op.affected_helix_ids.length
    if (op.target_ranges !== null) {
      list(op.target_ranges, MAX_SELECTORS); selectors += op.target_ranges.length
      for (const range of op.target_ranges) {
        shape(range, ['helix_id', 'start_bp', 'end_bp', 'direction', 'strand_id', 'domain_index'])
        if (!helices.has(range.helix_id)) fail('unresolved frozen deformation helix')
        bp(range.start_bp); bp(range.end_bp); direction(range.direction); nullableId(range.strand_id)
        if (range.strand_id !== null) {
          const domain = domainRef({ strand_id: range.strand_id, domain_index: range.domain_index }, strands)
          if (domain.helix_id !== range.helix_id || domain.direction !== range.direction
              || Math.min(range.start_bp, range.end_bp) < Math.min(domain.start_bp, domain.end_bp)
              || Math.max(range.start_bp, range.end_bp) > Math.max(domain.start_bp, domain.end_bp)) fail('frozen deformation range disagrees with its owner')
        }
        else if (range.domain_index !== null) fail('unowned frozen deformation domain')
      }
    }
    if (op.type === 'sweep') {
      shape(op.params, ['direction', 'start_step'])
      if (![1, -1].includes(op.params.direction)) fail('invalid sweep display direction')
      bp(op.params.start_step)
    } else if (op.type === 'twist') shape(op.params, [])
    else {
      shape(op.params, ['curvature_deg_per_bp', ...(Object.hasOwn(op.params, 'polymer_circle_count') ? ['polymer_circle_count'] : [])])
      if (!finite(op.params.curvature_deg_per_bp)) fail('invalid bend display provenance')
      if (Object.hasOwn(op.params, 'polymer_circle_count') && (!integer(op.params.polymer_circle_count) || op.params.polymer_circle_count < 1)) fail('invalid circle display provenance')
    }
  }
  if (selectors > MAX_SELECTORS) fail('DNA selector allowance exceeded')
  for (const crossover of topology.crossovers) {
    shape(crossover, ['id', 'half_a', 'half_b', 'extra_bases'])
    if (crossover.extra_bases !== null && crossover.extra_bases !== '') fail('unsupported inserted crossover bases')
    for (const half of [crossover.half_a, crossover.half_b]) {
      shape(half, ['helix_id', 'index', 'strand'])
      if (!expected.has(siteKey({ helix_id: half.helix_id, bp_index: half.index, direction: half.strand, copy_k: 0 }))) fail('unresolved crossover endpoint')
    }
  }
  for (const ligation of topology.forced_ligations) {
    shape(ligation, ['id', 'three_prime_helix_id', 'three_prime_bp', 'three_prime_direction', 'five_prime_helix_id', 'five_prime_bp', 'five_prime_direction', 'extra_bases', 'is_periodic_seam'])
    boolean(ligation.is_periodic_seam)
    if (ligation.extra_bases !== null && ligation.extra_bases !== '') fail('unsupported inserted ligation bases')
    for (const end of ['three_prime', 'five_prime']) if (!expected.has(siteKey({ helix_id: ligation[`${end}_helix_id`], bp_index: ligation[`${end}_bp`], direction: ligation[`${end}_direction`], copy_k: 0 }))) fail('unresolved ligation endpoint')
  }
  validateRecords(decodeDnaComparisonRecords(value.nucleotides), expected)
  validateAxes(value.helix_axes, helices, strands, overhangs, domains, scopedSamples)
  bounds(value.bounds_nm, value.nucleotides.length || value.helix_axes.length)
  return value
}

function validateRecords(records, expected) {
  list(records, MAX_SITES)
  const seen = new Set()
  for (const n of records) {
    shape(n, ['helix_id', 'bp_index', 'direction', 'copy_k', 'backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'placement_source', 'helical_site', 'strand_id', 'strand_type', 'is_five_prime', 'is_three_prime', 'domain_index', 'overhang_id', 'is_reference', 'is_flexible_segment', 'is_unpaired', 'slab_position', 'slab_quaternion'])
    const key = siteKey(n), owner = expected.get(key)
    if (!owner || seen.has(key) || n.strand_id !== owner.strand.id || n.strand_type !== owner.strand.strand_type || n.domain_index !== owner.index || n.overhang_id !== owner.domain.overhang_id || n.is_reference !== owner.strand.is_reference || n.is_flexible_segment !== false) fail('incomplete or ambiguous DNA record inventory')
    seen.add(key)
    for (const field of ['is_five_prime', 'is_three_prime', 'is_reference', 'is_unpaired']) boolean(n[field])
    for (const field of ['backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'slab_position']) vector(n[field], 3)
    vector(n.slab_quaternion, 4)
    if (n.placement_source !== 'native-full-o5-v1') fail('unsupported DNA placement authority')
    shape(n.helical_site, ['axis_point', 'radial_hat', 'azimuth_rad', 'groove_offset_rad', 'phase_roll_rad'])
    vector(n.helical_site.axis_point, 3); vector(n.helical_site.radial_hat, 3)
    if (!['azimuth_rad', 'groove_offset_rad', 'phase_roll_rad'].every(field => finite(n.helical_site[field]))) fail('nonfinite native DNA site')
  }
  if (seen.size !== expected.size) fail('omitted occupied DNA records')
}

function validateAxes(axes, helices, strands, overhangs, domains, scopedSamples) {
  list(axes, 16)
  const seen = new Set(), seenOverhangs = new Set(), coverage = new Map()
  let points = 0, segments = 0
  for (const axis of axes) {
    shape(axis, ['helix_id', 'start', 'end', 'samples', 'segments', ...(Object.hasOwn(axis, 'ovhg_axes') ? ['ovhg_axes'] : [])])
    if (!helices.has(axis.helix_id) || seen.has(axis.helix_id)) fail('ambiguous DNA axis')
    seen.add(axis.helix_id); vector(axis.start, 3); vector(axis.end, 3); list(axis.samples, 2048); list(axis.segments, MAX_SELECTORS)
    points += 2 + axis.samples.length; segments += axis.segments.length
    for (const point of axis.samples) vector(point, 3)
    for (const segment of axis.segments) {
      shape(segment, ['strand_id', 'domain_index', 'ovhg_id', 'bp_lo', 'bp_hi', 'start', 'end',
        ...(Object.hasOwn(segment, 'domain_ids') ? ['domain_ids'] : []),
        ...(scopedSamples && Object.hasOwn(segment, 'samples') ? ['samples'] : [])])
      vector(segment.start, 3); vector(segment.end, 3); points += 2
      if (scopedSamples && Object.hasOwn(segment, 'samples')) {
        list(segment.samples, 2048); points += segment.samples.length
        for (const point of segment.samples) vector(point, 3)
      }
      if (points > 2048 || segments > MAX_SELECTORS) fail('DNA axis allowance exceeded')
      const refs = segment.domain_ids?.length ? segment.domain_ids : (segment.strand_id === null ? [] : [{ strand_id: segment.strand_id, domain_index: segment.domain_index }])
      list(refs, 256)
      for (const ref of refs) {
        const domain = domainRef(ref, strands)
        bp(segment.bp_lo); bp(segment.bp_hi)
        if (domain.helix_id !== axis.helix_id || segment.bp_lo > segment.bp_hi || segment.bp_lo < Math.min(domain.start_bp, domain.end_bp) || segment.bp_hi > Math.max(domain.start_bp, domain.end_bp)) fail('invalid DNA axis segment owner')
        const key = ownerKey(ref.strand_id, ref.domain_index), covered = coverage.get(key) ?? new Set()
        for (let value = segment.bp_lo; value <= segment.bp_hi; value++) covered.add(value)
        coverage.set(key, covered)
      }
    }
    if (axis.ovhg_axes !== undefined) {
      if (!axis.ovhg_axes || Object.getPrototypeOf(axis.ovhg_axes) !== Object.prototype || Object.keys(axis.ovhg_axes).length > MAX_SELECTORS) fail('invalid overhang axes')
      for (const [id, entry] of Object.entries(axis.ovhg_axes)) {
        if (overhangs.get(id)?.helix_id !== axis.helix_id || seenOverhangs.has(id)) fail('unresolved overhang axis')
        seenOverhangs.add(id); shape(entry, ['bp_min', 'bp_max', 'start', 'end'])
        bp(entry.bp_min); bp(entry.bp_max); vector(entry.start, 3); vector(entry.end, 3); points += 2
      }
    }
    if (points > 2048 || segments > MAX_SELECTORS) fail('DNA axis allowance exceeded')
  }
  if (seen.size !== helices.size || seenOverhangs.size !== overhangs.size) fail('omitted authored DNA axes')
  for (const [key, domain] of domains) {
    const values = coverage.get(key)
    if (!values || values.size !== Math.abs(domain.end_bp - domain.start_bp) + 1) fail('omitted occupied DNA axis segments')
  }
}
