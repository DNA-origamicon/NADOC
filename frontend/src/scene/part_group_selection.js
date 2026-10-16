/** Typed interaction scope. Organizational groups never resolve as placements. */
import { canonicalSelection } from './selection_model.js'
import { clusterIdForNucleotide, clusterMemberFilter } from './cluster_entries.js'
import { hasOrganization, partGroupById, partGroupIdsForNucleotide, partGroupMemberFilter } from './part_group_display.js'

export function sceneGroupRef(nuc, design, { mode = 'groups', selection } = {}) {
  if (hasOrganization(design) && mode !== 'placements') {
    const ids = partGroupIdsForNucleotide(nuc, design)
    const selected = canonicalSelection(selection).items.find(ref => ref.kind === 'part_group' && ids.includes(ref.id))
    const id = selected?.id ?? ids[0]
    return id == null ? null : { kind: 'part_group', id }
  }
  const id = clusterIdForNucleotide(nuc, design)
  return id == null ? null : { kind: 'cluster', id }
}

export function groupRefMemberFilter(ref, design) {
  if (ref?.kind === 'part_group') return partGroupMemberFilter(partGroupById(design, ref.id), design)
  if (ref?.kind === 'cluster') return clusterMemberFilter(design?.cluster_transforms?.find(c => c.id === ref.id), design) ?? (() => false)
  return () => false
}

/** Explicit domain membership for context-menu grouping; never widens a domain
 * selection to every strand on its helix. Bounds are validated again by native commands. */
export function groupSelectionMembers(design, refs) {
  if (!hasOrganization(design)) throw new Error('Group organization is not active')
  if (!Array.isArray(refs) || refs.length > 30000 || (design.strands?.length ?? 0) > 30000 || (design.helices?.length ?? 0) > 30000)
    throw new Error('The selected membership exceeds the group input limit.')
  const strands = new Map((design.strands ?? []).map(s => [s.id, s]))
  const helices = new Set((design.helices ?? []).map(h => h.id))
  const seen = new Set(), selectedStrands = new Set(), helixIds = new Set(), domainIds = []
  const add = (strandId, index) => {
    const domain = Number.isSafeInteger(index) && index >= 0 ? strands.get(strandId)?.domains?.[index] : null
    if (!domain || !helices.has(domain.helix_id)) throw new Error('Selected domain no longer exists')
    const key = JSON.stringify([strandId, index])
    if (seen.has(key)) return
    seen.add(key); helixIds.add(domain.helix_id)
    domainIds.push({ strand_id: strandId, domain_index: index })
    if (domainIds.length > 30000) throw new Error('The selected membership exceeds the group input limit.')
  }
  for (const ref of refs ?? []) {
    if (ref.kind === 'domain') add(ref.strandId, ref.domainIndex)
    else if (ref.kind === 'strand') {
      if (selectedStrands.has(ref.id)) continue
      selectedStrands.add(ref.id)
      const strand = strands.get(ref.id)
      if (!strand) throw new Error('Selected strand no longer exists')
      strand.domains?.forEach((_, index) => add(strand.id, index))
    } else throw new Error('Select strands or domains to create or regroup')
  }
  if (!domainIds.length) throw new Error('Select strands or domains to create or regroup')
  return { helix_ids: [...helixIds], domain_ids: domainIds }
}

/** Interaction bounds only; named provenance is sent unchanged for native resolution. */
export function partGroupRanges(design, id) {
  const group = partGroupById(design, id)
  if (!group) throw new Error('Selected group no longer exists')
  const helices = new Map((design.helices ?? []).map(h => [h.id, h]))
  const ranges = []
  if (group.domain_ids?.length) {
    const strands = new Map((design.strands ?? []).map(s => [s.id, s]))
    for (const ref of group.domain_ids) {
      const d = Number.isSafeInteger(ref.domain_index) && ref.domain_index >= 0 ? strands.get(ref.strand_id)?.domains?.[ref.domain_index] : null
      if (!d || !helices.has(d.helix_id) || !Number.isSafeInteger(d.start_bp) || !Number.isSafeInteger(d.end_bp)) throw new Error('Selected group has a missing or invalid domain')
      ranges.push({ helixId: d.helix_id, lo: Math.min(d.start_bp, d.end_bp), hi: Math.max(d.start_bp, d.end_bp) })
    }
  } else for (const id of group.helix_ids ?? []) {
    const h = helices.get(id), lo = h?.bp_start ?? 0
    if (!h || !Number.isSafeInteger(lo) || !Number.isSafeInteger(h.length_bp) || h.length_bp < 1 || !Number.isSafeInteger(lo + h.length_bp - 1)) throw new Error('Selected group has a missing or invalid helix')
    ranges.push({ helixId: id, lo, hi: lo + h.length_bp - 1 })
  }
  if (!ranges.length) throw new Error('Selected group has no members')
  return ranges
}
