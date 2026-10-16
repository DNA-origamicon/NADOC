/** Organizational display only. Numerical placement owners never enter this view.
 * Store designs are immutable snapshots; indexes are built once per snapshot,
 * and style signatures once per organization object (including during pose drags).
 */
const snapshots = new WeakMap()
const signatures = new WeakMap()
const domainKey = (sid, index) => `d:${sid}:${index}`
const helixKey = id => `h:${id}`
const validColor = value => typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value)

export const hasOrganization = design => design?.group_organization != null
export function displayGroups(design) {
  if (!hasOrganization(design)) return design?.cluster_transforms ?? []
  const value = design.group_organization
  return value.version === 1 && Array.isArray(value.groups) ? value.groups : []
}

function topology(design) {
  const strands = new Map((design?.strands ?? []).map(strand => [strand.id, strand]))
  const domainExtensions = new Map(), helixExtensions = new Map()
  const append = (map, key, value) => {
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(value)
  }
  for (const ext of design?.extensions ?? []) {
    const strand = strands.get(ext.strand_id)
    const index = ext.end === 'five_prime' ? 0 : strand?.domains?.length - 1
    const terminal = strand?.domains?.[index]
    if (!terminal || !['five_prime', 'three_prime'].includes(ext.end)) continue
    const key = helixKey(`__ext_${ext.id}`)
    append(domainExtensions, domainKey(strand.id, index), key)
    append(helixExtensions, terminal.helix_id, key)
  }
  return { strands, domainExtensions, helixExtensions }
}

function compileGroup(group, index) {
  const keys = new Set()
  if (group?.domain_ids?.length) {
    for (const ref of group.domain_ids) {
      const key = domainKey(ref.strand_id, ref.domain_index)
      keys.add(key)
      for (const extension of index.domainExtensions.get(key) ?? []) keys.add(extension)
    }
  } else {
    for (const id of group?.helix_ids ?? []) {
      keys.add(helixKey(id))
      for (const extension of index.helixExtensions.get(id) ?? []) keys.add(extension)
    }
  }
  const member = nucleotide => Boolean(nucleotide && (
    keys.has(domainKey(nucleotide.strand_id, nucleotide.domain_index)) ||
    keys.has(helixKey(nucleotide.helix_id))))
  return { keys, member }
}

function snapshot(design) {
  let result = snapshots.get(design)
  if (result) return result
  const index = topology(design), groups = displayGroups(design)
  const byId = new Map(), compiled = new WeakMap(), members = new Map()
  const color = new Map(), alpha = new Map()
  const auto = group => group.auto_created === true || (group.auto_created == null && group.is_default === true)
  const better = (candidate, held) => {
    if (held === undefined) return true
    const a = groups[candidate], b = groups[held]
    if (auto(a) !== auto(b)) return !auto(a)
    if (validColor(a.color) !== validColor(b.color)) return validColor(a.color)
    return true
  }
  groups.forEach((group, position) => {
    byId.set(group.id, group)
    const item = compileGroup(group, index)
    compiled.set(group, item)
    for (const key of item.keys) {
      if (!members.has(key)) members.set(key, [])
      members.get(key).push(position)
      if (better(position, color.get(key))) color.set(key, position)
      const value = group.opacity
      if (typeof value === 'number' && value < 1) {
        alpha.set(key, Math.min(alpha.get(key) ?? 1, Math.max(0, value)))
      }
    }
  })
  for (const [terminal, extensions] of index.domainExtensions) {
    // An extension follows the exact terminal domain, including its color tier.
    // The terminal lookup avoids a later whole-helix group overriding a domain
    // color on the tail when it cannot override that same color on the body.
    const separator = terminal.lastIndexOf(':')
    const sid = terminal.slice(2, separator), di = Number(terminal.slice(separator + 1))
    const domain = index.strands.get(sid)?.domains?.[di]
    const winner = color.get(terminal) ?? color.get(helixKey(domain?.helix_id))
    if (winner !== undefined) for (const extension of extensions) color.set(extension, winner)
  }
  // Existing renderers resolve domain keys before helix keys. Materialize their
  // minimum here so overlapping group fades do not change that legacy policy.
  for (const strand of index.strands.values()) {
    strand.domains?.forEach((domain, di) => {
      const key = domainKey(strand.id, di)
      const minimum = Math.min(alpha.get(key) ?? 1, alpha.get(helixKey(domain.helix_id)) ?? 1)
      if (minimum < 1) alpha.set(key, minimum)
    })
  }
  const lookup = (map, nuc) => map.get(domainKey(nuc?.strand_id, nuc?.domain_index)) ??
    map.get(helixKey(nuc?.helix_id))
  result = { ...index, groups, byId, compiled, members, alpha,
    colorIndex: nuc => lookup(color, nuc), alphaFor: nuc => lookup(alpha, nuc) ?? 1,
    nucleotideValues: new Map() }
  snapshots.set(design, result)
  return result
}

export function partGroupById(design, id) {
  return hasOrganization(design) ? snapshot(design).byId.get(id) ?? null : null
}

function groupData(group, design) {
  if (!group || !design) return { keys: new Set(), member: () => false }
  const index = snapshot(design)
  let value = index.compiled.get(group)
  if (!value) {
    value = compileGroup(group, index)
    index.compiled.set(group, value)
  }
  return value
}

export const partGroupMemberFilter = (group, design) => groupData(group, design).member
export const partGroupNucKeys = (group, design) => new Set(groupData(group, design).keys)

export function partGroupIdsForNucleotide(nuc, design) {
  if (!hasOrganization(design) || !nuc) return []
  const data = snapshot(design)
  return [...new Set([
    ...(data.members.get(domainKey(nuc.strand_id, nuc.domain_index)) ?? []),
    ...(data.members.get(helixKey(nuc.helix_id)) ?? []),
  ])].sort((a, b) => a - b).map(index => data.groups[index].id)
}

export function partGroupNucKeysFor(design, ids) {
  const out = new Set()
  if (!hasOrganization(design)) return out
  let data
  for (const id of ids ?? []) {
    data ??= snapshot(design)
    const group = data.byId.get(id)
    if (group) for (const key of data.compiled.get(group).keys) out.add(key)
  }
  return out
}

export const partGroupColorIndex = design => snapshot(design).colorIndex
export const partGroupAlphaKeys = design => new Map(snapshot(design).alpha)

/** Atom/surface keys are expanded only on demand, once per immutable snapshot. */
export function partGroupNucleotideValues(design, kind) {
  const data = snapshot(design)
  if (data.nucleotideValues.has(kind)) return data.nucleotideValues.get(kind)
  const values = new Map(), resolve = kind === 'alpha' ? data.alphaFor : data.colorIndex
  for (const strand of data.strands.values()) {
    strand.domains?.forEach((domain, domain_index) => {
      const value = resolve({ helix_id: domain.helix_id, strand_id: strand.id, domain_index })
      if (value == null || (kind === 'alpha' && value === 1)) return
      for (let bp = Math.min(domain.start_bp, domain.end_bp); bp <= Math.max(domain.start_bp, domain.end_bp); bp++) {
        values.set(`${domain.helix_id}:${bp}:${domain.direction}`, value)
      }
    })
  }
  for (const ext of design.extensions ?? []) {
    const value = resolve({ helix_id: `__ext_${ext.id}` })
    if (value != null && !(kind === 'alpha' && value === 1)) values.set(`__ext_${ext.id}`, value)
  }
  data.nucleotideValues.set(kind, values)
  return values
}

export function partGroupDisplaySignature(design) {
  const organization = design.group_organization
  let signature = signatures.get(organization)
  if (signature === undefined) {
    signature = `part-groups:${JSON.stringify(displayGroups(design).map(group => [
      group.id, group.color ?? null, group.opacity ?? 1, group.auto_created, group.is_default,
      group.helix_ids ?? [], group.domain_ids ?? [],
    ]))}`
    signatures.set(organization, signature)
  }
  return signature
}

export function withPartGroupDisplay(design, id, patch) {
  if (!partGroupById(design, id)) return design
  return { ...design, group_organization: { ...design.group_organization,
    groups: displayGroups(design).map(group => group.id !== id ? group : {
      ...group,
      ...(patch?.color !== undefined ? { color: patch.color === '' ? null : patch.color } : {}),
      ...(patch?.opacity !== undefined ? { opacity: patch.opacity } : {}),
    }),
  } }
}
