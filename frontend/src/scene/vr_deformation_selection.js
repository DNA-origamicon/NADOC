import { clusterIdForNucleotide } from './cluster_entries.js'
import { vrInitialSelectionOwnerTokens } from './selection_hit_resolver.js'

// Session-only identity for the entire canonical set. A change to any member
// invalidates queued native drafts, even when the primary ref stays the same.
let signature = ''
let generation = 0
const session = Math.random().toString(36).slice(2)
export function vrDeformationSelection(items = []) {
  const next = JSON.stringify(items)
  if (next !== signature) { signature = next; generation++ }
  if (items.length < 2 || items.some(ref => !['cluster', 'strand', 'domain'].includes(ref.kind))) return null
  const identity = `selection:${session}:${generation}`
  return { identity, selectionKind: 'selection', ownerTokens: [identity],
    selectedRef: { kind: 'selection' }, selectedRefs: items.map(ref => ({ ...ref })),
    selectedOwnerTokens: items.flatMap(vrInitialSelectionOwnerTokens) }
}
export function resolveVRDeformationSelection(snapshot, items) {
  const target = vrDeformationSelection(items)
  return target && snapshot?.identity === target.identity && snapshot.selectionKind === 'selection' &&
    JSON.stringify(snapshot.ownerTokens) === JSON.stringify(target.ownerTokens) ? target : null
}

/** Native identities resolve against live topology, independent of desktop LOD. */
export function vrDeformationRefForOwner(owner, level, design, geometry) {
  if (!['cluster', 'strand', 'domain'].includes(level)) return null
  const nucleotide = owner?.nucleotide ?? (owner?.kind === 'domain' ? geometry?.find(n =>
    n.strand_id === owner.ref.strandId && (n.domain_index ?? 0) === owner.ref.domainIndex) : null)
  if (!nucleotide) return null
  if (level === 'cluster') {
    const id = clusterIdForNucleotide(nucleotide, design)
    return id ? { kind: 'cluster', id } : null
  }
  if (level === 'strand') return { kind: 'strand', id: nucleotide.strand_id }
  if (nucleotide.overhang_id) return null
  return { kind: 'domain', strandId: nucleotide.strand_id, domainIndex: nucleotide.domain_index ?? 0 }
}
