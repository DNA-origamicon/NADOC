/** Geometry/topology projection used by camera navigation when references are hidden. */

export function referenceGeometryHidden(state) {
  return state?.showReferenceGeometry === false || state?.simulationTabActive === true
}

export function referenceStrandIds(design) {
  return new Set((design?.strands ?? []).filter(s => s?.is_reference).map(s => s.id))
}

/** Keep only geometry that is actually visible to the camera controls. */
export function navigationGeometry(state) {
  const geometry = state?.currentGeometry ?? []
  if (!referenceGeometryHidden(state)) return geometry
  const refs = referenceStrandIds(state?.currentDesign)
  if (refs.size === 0) return geometry
  return geometry.filter(n => !refs.has(n?.strand_id))
}

const _projectedDesigns = new WeakMap()

/**
 * Remove helix axes occupied exclusively by reference strands. Multiscale orbit
 * uses these axes to choose its zoom/pan scale, so invisible reference helpers
 * must not remain in that distance field.
 */
export function navigationDesign(state) {
  const design = state?.currentDesign
  if (!design || !referenceGeometryHidden(state)) return design

  const cached = _projectedDesigns.get(design)
  if (cached) return cached

  const usedHelices = new Set()
  for (const strand of design.strands ?? []) {
    if (strand?.is_reference) continue
    for (const domain of strand?.domains ?? []) {
      if (domain?.helix_id != null) usedHelices.add(domain.helix_id)
    }
  }
  const projected = {
    ...design,
    helices: (design.helices ?? []).filter(h => usedHelices.has(h?.id)),
  }
  _projectedDesigns.set(design, projected)
  return projected
}
