/** Pure hit-metadata → canonical SelectionRef resolution. */

import { atomBaseKey, baseKey } from './base_ref.js'

function decodedIdentity(identity) {
  if (typeof identity !== 'string' || !identity) return null
  try { return decodeURIComponent(identity) } catch { return null }
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
    for (const primitive of ['bead', 'slab']) {
      const prefix = `flex:${connection.id}:${primitive}:`
      if (!decoded.startsWith(prefix)) continue
      const index = Number(decoded.slice(prefix.length))
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
    for (const primitive of ['bead', 'slab']) {
      const prefix = `linker:${connection.id}:ss:${primitive}:`
      if (!decoded.startsWith(prefix)) continue
      const index = Number(decoded.slice(prefix.length))
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
  }
  return null
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
