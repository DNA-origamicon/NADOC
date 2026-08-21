/** Pure hit-metadata → canonical SelectionRef resolution. */

import { atomBaseKey, baseKey, parseBaseKey } from './base_ref.js'
import { selectionRefKey } from './selection_ref.js'

function decodedIdentity(identity) {
  if (typeof identity !== 'string' || !identity) return null
  try { return decodeURIComponent(identity) } catch { return null }
}

function semanticIdentityPayload(decoded, prefix) {
  if (!decoded?.startsWith(prefix)) return null
  try { return JSON.parse(decoded.slice(prefix.length)) } catch { return null }
}

function semanticAtomRef(value) {
  return Array.isArray(value) && value.length === 2 &&
    value.every(item => typeof item === 'string' && item)
    ? { baseKey: value[0], name: value[1] }
    : null
}

function extraBaseOwner(key, design, extra = {}) {
  const ref = parseBaseKey(key)
  if (ref?.helix_id !== '__xb__' || !Number.isInteger(ref.k) || ref.k < 0) return null
  const connections = [
    ...(design?.crossovers ?? []).map(connection => [connection, 'crossover']),
    ...(design?.forced_ligations ?? []).map(connection => [connection, 'forced_ligation']),
  ]
  const match = connections.find(([connection]) =>
    String(connection.id) === ref.crossover_id &&
    ref.k < String(connection.extra_bases ?? '').length)
  return match ? {
    kind: 'extra_base', connectionId: match[0].id, connectionSubtype: match[1],
    ref: { kind: 'base', key }, ...extra,
  } : null
}

function nucleotidePrimitiveOwner(nuc) {
  const copy = nuc?.copy_k || nuc?.ext_k || 0
  return [
    'nuc',
    nuc?.strand_id || '_',
    Number(nuc?.domain_index || 0),
    nuc?.helix_id || '_',
    Number(nuc?.bp_index || 0),
    nuc?.direction || '_',
    Number(copy),
  ].join(':')
}

/** Resolve a native scene identity against live topology without delimiter parsing.
 * IDs may themselves contain colons, so candidates are reconstructed from the live
 * geometry/design and compared as complete semantic-owner prefixes. */
export function vrPrimitiveOwner(identity, { geometry = [], design = null } = {}) {
  const decoded = decodedIdentity(identity)
  if (!decoded) return null

  const semanticExtra = semanticIdentityPayload(decoded, 'extra-base-ref:')
  if (Array.isArray(semanticExtra) && semanticExtra.length === 2 &&
      typeof semanticExtra[0] === 'string') {
    return extraBaseOwner(semanticExtra[0], design, { primitive: semanticExtra[1] })
  }

  const semanticAtom = semanticAtomRef(semanticIdentityPayload(decoded, 'atom-ref:'))
  if (semanticAtom) {
    const nucleotide = (geometry ?? []).find(candidate =>
      atomBaseKey(candidate) === semanticAtom.baseKey)
    if (nucleotide) return {
      kind: 'atom', nucleotide,
      ref: { kind: 'base', key: semanticAtom.baseKey },
      atomRef: semanticAtom,
    }
    return extraBaseOwner(semanticAtom.baseKey, design, {
      primitive: 'atom', atomRef: semanticAtom,
    })
  }

  for (const nucleotide of geometry ?? []) {
    const owner = nucleotidePrimitiveOwner(nucleotide)
    if (decoded === owner || decoded.startsWith(`${owner}:`)) {
      const key = atomBaseKey(nucleotide)
      return key ? {
        kind: 'nucleotide',
        nucleotide,
        ref: { kind: 'base', key },
      } : null
    }
    const key = atomBaseKey(nucleotide)
    if (key && decoded.startsWith('atom:') && decoded.includes(`:base:${key}:`)) {
      return {
        kind: 'atom',
        nucleotide,
        ref: { kind: 'base', key },
      }
    }
  }

  const geometryOwners = (geometry ?? []).map(nucleotide => ({
    nucleotide,
    owner: nucleotidePrimitiveOwner(nucleotide),
    key: atomBaseKey(nucleotide),
  })).filter(candidate => candidate.key)

  const semanticBond = semanticIdentityPayload(decoded, 'atom-bond-ref:')
  if (Array.isArray(semanticBond) && semanticBond.length === 2) {
    const atomRefs = semanticBond.map(semanticAtomRef)
    if (atomRefs.every(Boolean)) {
      const first = geometryOwners.find(candidate => candidate.key === atomRefs[0].baseKey)
      const second = geometryOwners.find(candidate => candidate.key === atomRefs[1].baseKey)
      const firstExtra = first ? null : extraBaseOwner(atomRefs[0].baseKey, design)
      const secondExtra = second ? null : extraBaseOwner(atomRefs[1].baseKey, design)
      if ((!first && !firstExtra) || (!second && !secondExtra)) return null
      if (firstExtra || secondExtra) {
        const owner = firstExtra ?? secondExtra
        return {
          ...owner, primitive: 'atom-bond', atomRefs,
        }
      }
      if (first.key === second.key) {
        return {
          kind: 'atom_bond_base', nucleotide: first.nucleotide,
          ref: { kind: 'base', key: first.key }, atomRefs,
        }
      }
      return {
        kind: 'atom_bond',
        fromNucleotide: first.nucleotide,
        toNucleotide: second.nucleotide,
        ref: {
          kind: 'bond', fromKey: first.key, toKey: second.key,
          ...(first.nucleotide.strand_id === second.nucleotide.strand_id
            ? { strandId: first.nucleotide.strand_id } : {}),
        },
        atomRefs,
      }
    }
  }

  for (const first of geometryOwners) {
    const prefix = `backbone:${first.owner}~`
    if (!decoded.startsWith(prefix)) continue
    const second = geometryOwners.find(candidate => decoded === `${prefix}${candidate.owner}`)
    if (!second) return null
    return {
      kind: 'backbone_bond',
      fromNucleotide: first.nucleotide,
      toNucleotide: second.nucleotide,
      ref: {
        kind: 'bond', fromKey: first.key, toKey: second.key,
        ...(first.nucleotide.strand_id === second.nucleotide.strand_id
          ? { strandId: first.nucleotide.strand_id } : {}),
      },
    }
  }

  for (const first of geometryOwners) {
    const prefix = `atom-bond:bases:${first.key}~`
    if (!decoded.startsWith(prefix)) continue
    const second = geometryOwners.find(candidate =>
      decoded.startsWith(`${prefix}${candidate.key}:atoms:`))
    if (!second) return null
    if (first.key === second.key) {
      return {
        kind: 'atom_bond_base', nucleotide: first.nucleotide,
        ref: { kind: 'base', key: first.key },
      }
    }
    return {
      kind: 'atom_bond',
      fromNucleotide: first.nucleotide,
      toNucleotide: second.nucleotide,
      ref: {
        kind: 'bond', fromKey: first.key, toKey: second.key,
        ...(first.nucleotide.strand_id === second.nucleotide.strand_id
          ? { strandId: first.nucleotide.strand_id } : {}),
      },
    }
  }

  const connectionCollections = [
    ['crossover', design?.crossovers ?? [], 'crossover'],
    ['ligation', design?.forced_ligations ?? [], 'forced_ligation'],
    ['warning', design?.crossovers ?? [], 'crossover'],
  ]
  for (const [prefix, connections, subtype] of connectionCollections) {
    // Full-prefix comparison handles connection IDs containing ':' safely.
    const match = [...connections]
      .sort((a, b) => String(b.id).length - String(a.id).length)
      .find(connection => decoded.startsWith(`${prefix}:${connection.id}:`))
    if (match) {
      return {
        kind: 'crossover',
        ref: { kind: 'crossover', id: match.id, subtype },
      }
    }
  }

  for (const strand of design?.strands ?? []) {
    for (let domainIndex = 0; domainIndex < (strand.domains?.length ?? 0); domainIndex++) {
      const domain = strand.domains[domainIndex]
      const owner = `segment:${domain.helix_id}:${strand.id}:${domainIndex}:`
      if (decoded.startsWith(owner)) {
        return {
          kind: 'domain',
          ref: { kind: 'domain', strandId: strand.id, domainIndex },
        }
      }
    }
  }

  const strands = new Map((design?.strands ?? []).map(strand => [strand.id, strand]))
  for (const connection of design?.flexible_connections ?? []) {
    for (const primitive of ['bead', 'slab', 'backbone']) {
      const prefix = `flex:${connection.id}:${primitive}:`
      if (!decoded.startsWith(prefix)) continue
      const suffix = decoded.slice(prefix.length)
      const index = primitive === 'backbone'
        ? Number(suffix.match(/^\d+:near:(\d+)$/)?.[1])
        : Number(suffix)
      const anchor = connection.segment_bead_keys?.[index]
      const domain = strands.get(anchor?.strand_id)?.domains?.[anchor?.domain_index]
      if (!domain || !Number.isInteger(index)) return null
      const key = baseKey({
        helix_id: domain.helix_id,
        bp_index: anchor.bp_index,
        direction: anchor.direction,
      })
      return key ? {
        kind: 'flexible_base', connectionId: connection.id,
        ref: { kind: 'base', key },
      } : null
    }
  }

  for (const connection of design?.overhang_connections ?? []) {
    for (const primitive of ['bead', 'slab', 'backbone']) {
      const prefix = `linker:${connection.id}:ss:${primitive}:`
      if (!decoded.startsWith(prefix)) continue
      const suffix = decoded.slice(prefix.length)
      const index = primitive === 'backbone'
        ? Number(suffix.match(/^\d+:near:(\d+)$/)?.[1])
        : Number(suffix)
      if (!Number.isInteger(index) || index < 0) return null
      return {
        kind: 'linker_base', connectionId: connection.id,
        ref: {
          kind: 'base',
          key: baseKey({
            helix_id: `__lnk__${connection.id}`,
            bp_index: index,
            direction: 'FORWARD',
          }),
        },
      }
    }
    if (decoded.startsWith(`linker:${connection.id}:ds:`)) {
      return { kind: 'linker_connection', connectionId: connection.id, ref: null }
    }
  }
  return null
}

/** Resolve one native primitive to an exact global deformation-plane bp.
 *
 * A plane pick is deliberately stricter than ordinary selection. Only a live,
 * physical nucleotide (or atom wholly owned by that nucleotide) supplies an
 * unambiguous lattice cross-section. Domain cylinders, bonds spanning two bps,
 * crossovers, flexible/linker visuals, extensions, and crossover-insert copies
 * fail closed instead of being rounded to a nearby plane.
 */
export function vrDeformationPlanePick(identity, { geometry = [], design = null } = {}) {
  const owner = vrPrimitiveOwner(identity, { geometry, design })
  if (!owner) return { resolved: false, reason: 'invalid_primitive' }

  let nucleotide = null
  if (['nucleotide', 'atom', 'atom_bond_base'].includes(owner.kind)) {
    nucleotide = owner.nucleotide
  } else if (owner.kind === 'backbone_bond' || owner.kind === 'atom_bond') {
    const first = owner.fromNucleotide
    const second = owner.toNucleotide
    if (first?.helix_id === second?.helix_id &&
        first?.bp_index === second?.bp_index) nucleotide = first
    else return { resolved: false, reason: 'ambiguous_primitive' }
  } else {
    return { resolved: false, reason: 'ambiguous_primitive' }
  }

  const helixId = nucleotide?.helix_id
  const bp = nucleotide?.bp_index
  if (typeof helixId !== 'string' || !helixId || helixId.startsWith('__') ||
      !Number.isSafeInteger(bp) || nucleotide?.extra_base_k != null ||
      nucleotide?.ext_k != null || Number(nucleotide?.copy_k ?? 0) !== 0) {
    return { resolved: false, reason: 'synthetic_not_supported' }
  }
  const helix = design?.helices?.find(candidate => candidate.id === helixId)
  const start = helix?.bp_start ?? 0
  const length = helix?.length_bp
  if (!helix || !Number.isSafeInteger(start) || !Number.isSafeInteger(length) ||
      length < 1 || bp < start || bp >= start + length) {
    return { resolved: false, reason: 'out_of_range' }
  }
  return { resolved: true, reason: 'resolved', bp, helixId }
}

/** Ordered opaque aliases for cross-representation selection projection. */
export function vrOwnerTokens({ selected = false, selectedRef = null, owner = null,
  nucleotide = null, key = null } = {}) {
  if (!selected || !selectedRef) return []
  const refs = [selectedRef]
  if (nucleotide) {
    if (key) refs.push({ kind: 'base', key })
    refs.push({
      kind: 'domain', strandId: nucleotide.strand_id,
      domainIndex: nucleotide.domain_index ?? 0,
    })
    refs.push({ kind: 'strand', id: nucleotide.strand_id })
  }
  if (owner?.ref?.kind === 'bond') {
    refs.push(
      { kind: 'base', key: owner.ref.fromKey },
      { kind: 'base', key: owner.ref.toKey },
    )
    if (owner.ref.strandId) refs.push({ kind: 'strand', id: owner.ref.strandId })
  }
  return [...new Set(refs
    .map(ref => selectionRefKey(ref))
    .filter(Boolean)
    .map(token => encodeURIComponent(token)))]
}

/** Encode the canonical desktop selection for a native viewer launched after the
 * selection was made. The exact ref is sufficient because selectable native
 * primitives advertise their canonical ref among their owner aliases. */
export function vrInitialSelectionOwnerTokens(selectedRef) {
  const token = selectionRefKey(selectedRef)
  return token ? [encodeURIComponent(token)] : []
}

/** Validate one native tool intent's action-time target against the current
 * canonical browser selection. Exact primitive identity is intentionally
 * transient: it can describe an atom/bond beneath a stable Base selection without
 * inventing a persistent design ref for renderer-owned data. */
export function vrToolTargetSnapshot({
  identity, selectionKind, ownerTokens, selectedRef, geometry = [], design = null,
} = {}) {
  const tokens = Array.isArray(ownerTokens)
    ? ownerTokens.filter(token => typeof token === 'string').slice(0, 8)
    : []
  const expectedToken = vrInitialSelectionOwnerTokens(selectedRef)[0] ?? null
  if (!selectedRef || typeof identity !== 'string' || !identity ||
      selectionKind !== selectedRef.kind || !expectedToken ||
      !tokens.includes(expectedToken)) return null
  const primitiveOwner = vrPrimitiveOwner(identity, { geometry, design })
  if (!primitiveOwner) return null
  return {
    identity,
    selectionKind,
    ownerTokens: [...tokens],
    selectedRef,
    primitiveKind: primitiveOwner.kind,
    primitiveRef: primitiveOwner.ref ?? null,
    ...(primitiveOwner.atomRef ? { atomRef: { ...primitiveOwner.atomRef } } : {}),
    ...(primitiveOwner.atomRefs
      ? { atomRefs: primitiveOwner.atomRefs.map(atom => ({ ...atom })) }
      : {}),
  }
}

/** Pure native-VR owner × selection-level acceptance policy.
 * Target existence and Cluster/End facts stay explicit so callers cannot report an
 * acknowledgement merely because an identity parsed successfully. */
export function vrSelectionAccepted(ownerKind, level, {
  hasTarget = true, isTerminal = false, hasCluster = false,
} = {}) {
  if (!hasTarget) return false
  if (['nucleotide', 'atom', 'atom_bond_base', 'domain'].includes(ownerKind)) {
    return ['default', 'strand', 'domain', 'base'].includes(level) ||
      (level === 'end' && isTerminal) || (level === 'cluster' && hasCluster)
  }
  if (ownerKind === 'backbone_bond' || ownerKind === 'atom_bond') {
    return level === 'default' || level === 'strand' ||
      (level === 'cluster' && hasCluster)
  }
  if (ownerKind === 'crossover') {
    return ['default', 'strand', 'xover'].includes(level) ||
      (level === 'cluster' && hasCluster)
  }
  if (ownerKind === 'extra_base') return level === 'base'
  return (ownerKind === 'flexible_base' || ownerKind === 'linker_base') && level === 'base'
}

export function crossoverRefForArc(arc, design) {
  const id = arc?.crossover_id
  if (!id) return null
  if (design?.crossovers?.some(xo => xo.id === id)) {
    return { kind: 'crossover', id, subtype: 'crossover' }
  }
  if (design?.forced_ligations?.some(fl => fl.id === id)) {
    return { kind: 'crossover', id, subtype: 'forced_ligation' }
  }
  return null
}

export function endRefForEntry(entry) {
  if (!entry?.nuc || !(entry.nuc.is_five_prime || entry.nuc.is_three_prime)) return null
  const key = baseKey(entry.nuc, entry._copy)
  return key ? { kind: 'end', key } : null
}

export function bondRefForCone(cone, strandId = cone?.strandId ?? null) {
  if (!cone?.fromNuc || !cone?.toNuc) return null
  const fromKey = baseKey(cone.fromNuc)
  const toKey = baseKey(cone.toNuc)
  if (!fromKey || !toKey) return null
  return {
    kind: 'bond', fromKey, toKey,
    ...(strandId ? { strandId } : {}),
  }
}

/** Resolve a stable canonical bond ref back to its current live cone adapter. */
export function coneForBondRef(cones, ref) {
  if (ref?.kind !== 'bond' || !Array.isArray(cones)) return null
  return cones.find(cone => {
    const candidate = bondRefForCone(cone, cone.strandId)
    return candidate?.fromKey === ref.fromKey && candidate?.toKey === ref.toKey &&
      (!ref.strandId || candidate.strandId === ref.strandId)
  }) ?? null
}
