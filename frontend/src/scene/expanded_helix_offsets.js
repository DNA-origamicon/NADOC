export const NATURAL_HELIX_SPACING_NM = 2.25
export const DEFAULT_EXPANDED_HELIX_SPACING_NM = 5.0

function _point(value) {
  return value && [value.x, value.y, value.z].every(Number.isFinite)
    ? [value.x, value.y, value.z] : null
}

/** Pure source of desktop Expanded Quick View's per-helix translations. */
export function expandedHelixOffsetFrame(
  design, spacingNm = DEFAULT_EXPANDED_HELIX_SPACING_NM,
) {
  const helices = Array.isArray(design?.helices) ? design.helices : []
  if (!helices.length || !Number.isFinite(spacingNm) || spacingNm <= 0) return null
  const rows = helices.map(helix => ({
    id: typeof helix?.id === 'string' ? helix.id : null,
    start: _point(helix?.axis_start),
    end: _point(helix?.axis_end),
  }))
  if (rows.some(row => !row.id || !row.start || !row.end)) return null

  const delta = rows[0].end.map((value, axis) => Math.abs(value - rows[0].start[axis]))
  // Preserve the desktop tie order: Z, then Y, then X.
  const axis = delta[2] >= delta[0] && delta[2] >= delta[1]
    ? 2 : delta[1] >= delta[0] && delta[1] >= delta[2] ? 1 : 0
  const lateral = [0, 1, 2].filter(candidate => candidate !== axis)
  const centroid = lateral.map(component =>
    rows.reduce((sum, row) => sum + row.start[component], 0) / rows.length)
  const scaleDelta = spacingNm / NATURAL_HELIX_SPACING_NM - 1
  const offsets = new Map(rows.map(row => {
    const offset = [0, 0, 0]
    for (let index = 0; index < lateral.length; index++) {
      const component = lateral[index]
      offset[component] = (row.start[component] - centroid[index]) * scaleDelta
    }
    return [row.id, offset]
  }))
  return { axis: ['X', 'Y', 'Z'][axis], offsets }
}
