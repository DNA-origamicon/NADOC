/** Pure hit-metadata → canonical SelectionRef resolution. */

import { baseKey } from './base_ref.js'

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
