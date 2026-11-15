import { isVisibleInstance } from './base_pick.js'

const HEAVY = new Set(['vdw', 'ballstick', 'stick', 'surface'])

/** Resolve every coarse highlight pool at composition time, never from stale glow output. */
export function coarseSelectionGeometry(entries, renderer) {
  const beads = [], cylinders = new Map()
  // Global atomistic/surface modes hide the coarse root. Position-only adapters
  // must not resurrect its geometry either.
  if (renderer.getHelixCtrl?.()?.root?.visible === false) return { beads, cylinders: [] }
  for (const entry of entries) {
    const nuc = entry.nuc ?? entry.arcData?.nucA
    if (nuc && HEAVY.has(renderer.columnRepAt?.(nuc.helix_id, nuc.bp_index))) continue
    if (nuc?.strand_id != null && nuc?.domain_index != null &&
        renderer.isDomainCylinder?.(nuc.strand_id, nuc.domain_index)) {
      cylinders.set(`${nuc.strand_id}:${nuc.domain_index}`,
        { strandId: nuc.strand_id, domainIndex: nuc.domain_index })
    } else if (!entry.instMesh || isVisibleInstance(entry.instMesh, entry.id)) beads.push(entry)
  }
  return { beads, cylinders: [...cylinders.values()] }
}

/** Connection arcs remain drawn in coarse cylinder views as well as Full/Beads. */
export function coarseConnectionVisible(arc, renderer) {
  return renderer.getHelixCtrl?.()?.root?.visible !== false &&
    [arc.fromNuc, arc.toNuc].every(nuc => !nuc ||
      !HEAVY.has(renderer.columnRepAt?.(nuc.helix_id, nuc.bp_index)))
}
