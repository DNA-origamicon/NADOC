/**
 * Stable, renderer-independent selection references.
 *
 * Phase-1 foundation for the mature selection model. This module deliberately owns
 * identity only: it does not define reducer ordering/toggle policy, end semantics,
 * forced-ligation classification, persistence, DOM behavior, or renderer highlights.
 * Those remain explicit decision gates in memory/project_selection_model.md.
 */

import { parseBaseKey } from './base_ref.js'

export const STABLE_SELECTION_KINDS = Object.freeze([
  'cluster', 'strand', 'domain', 'base', 'end', 'bond', 'crossover',
  'overhang', 'extension', 'protein',
])

export const CROSSOVER_SUBTYPES = Object.freeze(['crossover', 'forced_ligation'])
const CROSSOVER_TYPES = new Set(CROSSOVER_SUBTYPES)

const KINDS = new Set(STABLE_SELECTION_KINDS)
const nonEmptyString = (value) => typeof value === 'string' && value.length > 0

/** Return a minimal canonical ref, or null when the input cannot be stable identity. */
export function normalizeSelectionRef(input) {
  if (!input || typeof input !== 'object' || !KINDS.has(input.kind)) return null

  switch (input.kind) {
    case 'domain': {
      const strandId = input.strandId ?? input.strand_id
      const domainIndex = input.domainIndex ?? input.domain_index
      if (!nonEmptyString(strandId) || !Number.isInteger(domainIndex) || domainIndex < 0) return null
      return { kind: 'domain', strandId, domainIndex }
    }
    case 'base':
    case 'end': {
      if (!nonEmptyString(input.key) || !parseBaseKey(input.key)) return null
      return { kind: input.kind, key: input.key }
    }
    case 'bond': {
      if (!nonEmptyString(input.fromKey) || !parseBaseKey(input.fromKey) ||
          !nonEmptyString(input.toKey) || !parseBaseKey(input.toKey)) return null
      const strandId = input.strandId ?? input.strand_id
      return {
        kind: 'bond', fromKey: input.fromKey, toKey: input.toKey,
        ...(nonEmptyString(strandId) ? { strandId } : {}),
      }
    }
    case 'crossover': {
      if (!nonEmptyString(input.id)) return null
      const subtype = input.subtype ?? 'crossover'
      if (!CROSSOVER_TYPES.has(subtype)) return null
      return { kind: 'crossover', id: input.id, subtype }
    }
    default: {
      if (!nonEmptyString(input.id)) return null
      return { kind: input.kind, id: input.id }
    }
  }
}

/** Stable structural identity key; JSON tuple encoding avoids delimiter collisions. */
export function selectionRefKey(input) {
  const ref = normalizeSelectionRef(input)
  if (!ref) return null
  if (ref.kind === 'domain') return JSON.stringify(['domain', ref.strandId, ref.domainIndex])
  if (ref.kind === 'base' || ref.kind === 'end') return JSON.stringify([ref.kind, ref.key])
  if (ref.kind === 'bond') return JSON.stringify(['bond', ref.fromKey, ref.toKey, ref.strandId ?? null])
  if (ref.kind === 'crossover') return JSON.stringify(['crossover', ref.subtype, ref.id])
  return JSON.stringify([ref.kind, ref.id])
}

export function selectionRefsEqual(a, b) {
  const ak = selectionRefKey(a)
  return ak != null && ak === selectionRefKey(b)
}

/** Normalize and deduplicate while preserving first-seen order. Invalid refs drop. */
export function dedupeSelectionRefs(inputs = []) {
  if (!Array.isArray(inputs)) return []
  const seen = new Set()
  const refs = []
  for (const input of inputs) {
    const ref = normalizeSelectionRef(input)
    const key = selectionRefKey(ref)
    if (!key || seen.has(key)) continue
    seen.add(key)
    refs.push(ref)
  }
  return refs
}

/** Filter against live design identity without changing order or reference shape. */
export function reconcileSelectionRefs(inputs, isLive) {
  const refs = dedupeSelectionRefs(inputs)
  if (typeof isLive !== 'function') return refs
  return refs.filter(ref => isLive(ref) === true)
}

/** JSON-safe serialization boundary. Invalid refs never leave the process. */
export function serializeSelectionRefs(inputs) {
  return JSON.stringify(dedupeSelectionRefs(inputs))
}

/** Safe inverse of serializeSelectionRefs; corrupt or non-array input becomes empty. */
export function deserializeSelectionRefs(serialized) {
  try {
    const value = typeof serialized === 'string' ? JSON.parse(serialized) : serialized
    return Array.isArray(value) ? dedupeSelectionRefs(value) : []
  } catch {
    return []
  }
}

/** Determine whether a stable ref still has a live owner in the current design.
 * Base/end refs use conservative owner-level checks so representation changes and
 * temporary geometry rebuilds never erase a valid logical selection. */
export function isSelectionRefLive(input, design) {
  const ref = normalizeSelectionRef(input)
  if (!ref || !design) return false
  switch (ref.kind) {
    case 'strand': return !!design.strands?.some(s => s.id === ref.id)
    case 'domain': return !!design.strands?.find(s => s.id === ref.strandId)?.domains?.[ref.domainIndex]
    case 'overhang': return !!design.overhangs?.some(item => item.id === ref.id)
    case 'extension': return !!design.extensions?.some(item => item.id === ref.id)
    case 'cluster': return !!design.cluster_transforms?.some(item => item.id === ref.id)
    case 'protein': return !!design.protein_attachments?.some(item => item.id === ref.id)
    case 'crossover': {
      const collection = ref.subtype === 'forced_ligation' ? design.forced_ligations : design.crossovers
      return !!collection?.some(item => item.id === ref.id)
    }
    case 'bond':
      return isSelectionRefLive({ kind: 'base', key: ref.fromKey }, design) &&
        isSelectionRefLive({ kind: 'base', key: ref.toKey }, design)
    case 'base':
    case 'end': {
      const key = parseBaseKey(ref.key)
      if (!key) return false
      if (key.helix_id === '__xb__') return !!design.crossovers?.some(item => item.id === key.crossover_id)
      if (key.helix_id.startsWith('__ext_')) {
        return !!design.extensions?.some(item => item.id === key.helix_id.slice('__ext_'.length))
      }
      if (key.helix_id.startsWith('__lnk__')) {
        return !!design.overhang_connections?.some(item => item.id === key.helix_id.slice('__lnk__'.length))
      }
      return !!design.helices?.some(item => item.id === key.helix_id)
    }
    default: return false
  }
}
