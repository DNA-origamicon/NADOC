import { createTargetEntryMatcher } from './annotation_targets.js'

function mean(points) {
  if (!points.length) return null
  return [0, 1, 2].map(i => points.reduce((sum, p) => sum + p[i], 0) / points.length)
}

function domainMidpoint(entries) {
  const points = [...entries].sort((a, b) => a.nuc.bp_index - b.nuc.bp_index
    || (a.nuc.copy_k ?? 0) - (b.nuc.copy_k ?? 0)).map(({ nuc, pos }) => nuc.helical_site?.axis_point ?? pos)
  if (points.length < 2) return points[0] ?? null
  const lengths = points.slice(1).map((p, i) => Math.hypot(...p.map((value, j) => value - points[i][j])))
  let remaining = lengths.reduce((sum, length) => sum + length, 0) / 2
  for (let i = 0; i < lengths.length; i++) {
    if (lengths[i] > 0 && remaining <= lengths[i]) {
      return points[i].map((value, j) => value + (points[i + 1][j] - value) * remaining / lengths[i])
    }
    remaining -= lengths[i]
  }
  return points[0]
}

/** Position controls use the posed design frame, including curved helix centerlines. */
export function torqueSelectionCenter(state, { resolveBase, resolveExternal } = {}) {
  const refs = state.selection?.items || []
  const entries = (state.currentGeometry || []).map(nuc => ({ nuc, pos: nuc.backbone_position }))
  const match = createTargetEntryMatcher()
  const centers = []
  for (const ref of refs) {
    const matched = match([ref], state.currentDesign, entries)
    if (ref.kind === 'domain') {
      const point = domainMidpoint(matched)
      if (point) centers.push(point)
    } else if (['cluster', 'part_group', 'strand'].includes(ref.kind)) {
      const helices = new Map()
      for (const { nuc, pos } of matched) {
        if (!helices.has(nuc.helix_id)) helices.set(nuc.helix_id, [])
        helices.get(nuc.helix_id).push(nuc.helical_site?.axis_point ?? pos)
      }
      const point = mean([...helices.values()].map(mean))
      if (point) centers.push(point)
    } else if (matched.length) {
      centers.push(mean(matched.map(entry => entry.pos)))
    } else {
      const position = ref.key ? resolveBase?.(ref.key) : resolveExternal?.(ref)
      if (position) centers.push([position.x, position.y, position.z])
    }
  }
  return mean(centers)
}

export function torqueDesignCenter(geometry = []) {
  return mean((geometry || []).map(nuc => nuc.helical_site?.axis_point ?? nuc.backbone_position).filter(Boolean)) ?? [0, 0, 0]
}
