/** Geometry/topology projection shared by fitting, orbit and zoom. */
import { baseKey } from './base_ref.js'

const EMPTY_HIDDEN = new Set()

export function referenceGeometryHidden(state) {
  return state?.showReferenceGeometry === false || state?.simulationTabActive === true
}

export function referenceStrandIds(design) {
  return new Set((design?.strands ?? []).filter(s => s?.is_reference).map(s => s.id))
}

/** Raycast/proximity targets obey the same visibility contract as rendering. */
export function referenceStrandInteractionHidden(state, strandId) {
  if (!strandId || !referenceGeometryHidden(state)) return false
  return (state?.currentDesign?.strands ?? []).some(
    strand => strand?.id === strandId && strand?.is_reference)
}

/** Keep only geometry that is actually visible to the camera controls. */
export function navigationGeometry(state, hiddenBaseKeys = EMPTY_HIDDEN) {
  const geometry = state?.currentGeometry ?? []
  const refs = referenceGeometryHidden(state) ? referenceStrandIds(state?.currentDesign) : EMPTY_HIDDEN
  if (!refs.size && !hiddenBaseKeys.size && !state?.staplesHidden) return geometry
  return geometry.filter(n => !refs.has(n?.strand_id) &&
    !(state?.staplesHidden && n.strand_type !== 'scaffold') &&
    !hiddenBaseKeys.has(baseKey(n, n.copy_k ?? 0)))
}

const _projectedDesigns = new WeakMap()

/** Keep only visible axis intervals in the navigation speed/pivot field. */
export function navigationDesign(state, hiddenBaseKeys = EMPTY_HIDDEN) {
  const design = state?.currentDesign
  const refsHidden = referenceGeometryHidden(state)
  const staplesHidden = !!state?.staplesHidden
  if (!design || (!refsHidden && !staplesHidden && !hiddenBaseKeys.size)) return design
  const geometry = state?.currentGeometry
  const cached = _projectedDesigns.get(design)
  if (cached && cached.geometry === geometry && cached.hiddenBaseKeys === hiddenBaseKeys &&
      cached.refsHidden === refsHidden && cached.staplesHidden === staplesHidden) return cached.projected

  let helices
  if (geometry) {
    const visibleColumns = new Map()
    for (const nuc of navigationGeometry(state, hiddenBaseKeys)) {
      if (!Number.isFinite(nuc.bp_index)) continue
      let columns = visibleColumns.get(nuc.helix_id)
      if (!columns) visibleColumns.set(nuc.helix_id, columns = new Set())
      columns.add(nuc.bp_index)
    }
    helices = (design.helices ?? []).flatMap(helix => {
      const columns = [...(visibleColumns.get(helix.id) ?? [])].sort((a, b) => a - b)
      if (!columns.length) return []
      const runs = []
      for (const bp of columns) {
        const last = runs.at(-1)
        if (last && bp === last[1] + 1) last[1] = bp
        else runs.push([bp, bp])
      }
      const start = helix.axis_start, end = helix.axis_end
      if (!start || !end || !(helix.length_bp > 1)) return [helix]
      const point = bp => {
        const t = Math.max(0, Math.min(1, (bp - (helix.bp_start ?? 0)) / (helix.length_bp - 1)))
        return Object.fromEntries(['x', 'y', 'z'].map(k => [k, start[k] + (end[k] - start[k]) * t]))
      }
      return runs.map(([lo, hi]) => ({ ...helix, axis_start: point(lo), axis_end: point(hi) }))
    })
  } else {
    // Topology-only startup: reference filtering remains available before geometry arrives.
    const usedHelices = new Set()
    for (const strand of design.strands ?? []) {
      if ((refsHidden && strand.is_reference) || (staplesHidden && strand.strand_type !== 'scaffold')) continue
      for (const domain of strand.domains ?? []) usedHelices.add(domain.helix_id)
    }
    helices = (design.helices ?? []).filter(h => usedHelices.has(h.id))
  }
  const projected = { ...design, helices }
  _projectedDesigns.set(design, { geometry, hiddenBaseKeys, refsHidden, staplesHidden, projected })
  return projected
}
