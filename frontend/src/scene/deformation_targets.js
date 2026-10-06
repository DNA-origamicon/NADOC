import { canonicalSelection, createSelectionState } from './selection_model.js'

/** Resolve bounds for interaction only. The server validates and freezes membership. */
export function deformationTargets(state) {
  const targets = canonicalSelection(state).items
  const design = state.currentDesign
  const ranges = []
  const addDomain = (strandId, index) => {
    const d = design?.strands?.find(s => s.id === strandId)?.domains?.[index]
    if (!d) throw new Error('Selected domain no longer exists')
    ranges.push({ helixId: d.helix_id, lo: Math.min(d.start_bp, d.end_bp), hi: Math.max(d.start_bp, d.end_bp) })
  }
  try {
    for (const ref of targets) {
      if (ref.kind === 'domain') addDomain(ref.strandId, ref.domainIndex)
      else if (ref.kind === 'strand') {
        const strand = design?.strands?.find(s => s.id === ref.id)
        if (!strand) throw new Error('Selected strand no longer exists')
        strand.domains.forEach((_, i) => addDomain(strand.id, i))
      } else if (ref.kind === 'cluster') {
        const c = design?.cluster_transforms?.find(c => c.id === ref.id)
        if (!c) throw new Error('Selected cluster no longer exists')
        if (c.domain_ids?.length) c.domain_ids.forEach(d => addDomain(d.strand_id, d.domain_index))
        else for (const id of c.helix_ids ?? []) {
          const h = design?.helices?.find(h => h.id === id)
          if (!h) throw new Error('Selected helix no longer exists')
          ranges.push({ helixId: id, lo: h.bp_start ?? 0, hi: (h.bp_start ?? 0) + h.length_bp - 1 })
        }
      } else throw new Error('Select clusters, strands, or domains for Bend / Twist')
    }
    return { targets, ranges, error: ranges.length ? null : 'Select clusters, strands, or domains in the scene or lists.' }
  } catch (error) { return { targets, ranges: [], error: error.message } }
}

export function targetState(design, targets) {
  return { currentDesign: design, selection: createSelectionState({ items: targets }) }
}
