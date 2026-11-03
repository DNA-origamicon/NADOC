/** Domain endpoint edits shared by snap validation and the drag preview. */
export function crossoverDragEndpoints(group) {
  const endpoints = new Map()
  for (const { d0, d1 } of group) {
    endpoints.set(d0, { ...endpoints.get(d0), end: true })
    endpoints.set(d1, { ...endpoints.get(d1), start: true })
  }
  return endpoints
}

/** Check occupancy after applying every selected endpoint move simultaneously. */
export function crossoverDragFits(strands, endpoints, delta) {
  const tracks = new Map()
  for (const strand of strands) {
    if (strand.is_reference) continue
    for (const domain of strand.domains) {
      const edit = endpoints.get(domain)
      const start = domain.start_bp + (edit?.start ? delta : 0)
      const end = domain.end_bp + (edit?.end ? delta : 0)
      const key = `${domain.helix_id}_${domain.direction}`
      if (!tracks.has(key)) tracks.set(key, [])
      tracks.get(key).push([Math.min(start, end), Math.max(start, end)])
    }
  }
  for (const ranges of tracks.values()) {
    ranges.sort((a, b) => a[0] - b[0])
    for (let i = 1; i < ranges.length; i++) {
      if (ranges[i][0] <= ranges[i - 1][1]) return false
    }
  }
  return true
}
