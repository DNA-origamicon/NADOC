const VALID_RESOLUTIONS = new Set(['coarse', 'fine'])

function positionOf(nucleotide) {
  const position = nucleotide?.axis_position ?? nucleotide?.backbone_position ?? nucleotide?.base_position
  if (!Array.isArray(position) || position.length < 3) return null
  const values = position.slice(0, 3).map(Number)
  return values.every(Number.isFinite) ? values : null
}

function siteKey(nucleotide, resolution, coarseStarts) {
  const helix = nucleotide.helix_id ?? '__unmapped__'
  const copy = Number(nucleotide.copy) || 0
  const bp = Number(nucleotide.bp_index)
  if (Number.isFinite(bp)) {
    const start = coarseStarts.get(`${helix}:${copy}`) ?? 0
    const index = resolution === 'coarse' ? Math.floor((bp - start) / 5) : bp
    return `${helix}:${index}:${copy}`
  }
  return `${helix}:${String(nucleotide.bp_index ?? '')}:${nucleotide.direction ?? ''}:${copy}`
}

/**
 * Build the unsimulated mrDNA abstraction directly from NADOC render geometry.
 * Fine uses one site per base pair; coarse combines five adjacent base pairs.
 * Strand-order edges preserve backbone and crossover connectivity.
 */
export function buildMrdnaInputPreview(geometry, resolution) {
  if (!VALID_RESOLUTIONS.has(resolution) || !Array.isArray(geometry)) return { points: [], edges: [] }
  const coarseStarts = new Map()
  for (const nucleotide of geometry) {
    const bp = Number(nucleotide?.bp_index)
    if (!Number.isFinite(bp)) continue
    const key = `${nucleotide.helix_id ?? '__unmapped__'}:${Number(nucleotide.copy) || 0}`
    coarseStarts.set(key, Math.min(coarseStarts.get(key) ?? bp, bp))
  }
  const sites = new Map()
  const nucleotideSites = new Map()
  geometry.forEach((nucleotide, index) => {
    const position = positionOf(nucleotide)
    if (!position) return
    const key = siteKey(nucleotide, resolution, coarseStarts)
    let site = sites.get(key)
    if (!site) {
      site = { key, sum: [0, 0, 0], count: 0, first: index, helix: nucleotide.helix_id, bp: Number(nucleotide.bp_index) }
      sites.set(key, site)
    }
    for (let axis = 0; axis < 3; axis++) site.sum[axis] += position[axis]
    site.count++
    nucleotideSites.set(index, key)
  })
  const ordered = [...sites.values()].sort((a, b) => a.first - b.first)
  const indexByKey = new Map(ordered.map((site, index) => [site.key, index]))
  const points = ordered.map(site => ({
    x: site.sum[0] / site.count, y: site.sum[1] / site.count, z: site.sum[2] / site.count,
  }))

  const edgeKeys = new Set()
  const addEdge = (a, b) => {
    if (a === undefined || b === undefined || a === b) return
    const lo = Math.min(a, b), hi = Math.max(a, b)
    edgeKeys.add(`${lo}:${hi}`)
  }
  const byStrand = new Map()
  geometry.forEach((nucleotide, index) => {
    if (!nucleotideSites.has(index) || nucleotide.strand_id == null) return
    const strand = byStrand.get(nucleotide.strand_id) ?? []
    strand.push({
      site: indexByKey.get(nucleotideSites.get(index)),
      domain: Number(nucleotide.domain_index) || 0,
      bp: Number(nucleotide.bp_index) || 0,
      reverse: String(nucleotide.direction).toUpperCase() === 'REVERSE',
      first: index,
    })
    byStrand.set(nucleotide.strand_id, strand)
  })
  for (const strand of byStrand.values()) {
    strand.sort((a, b) => a.domain - b.domain ||
      (a.domain === b.domain ? (a.reverse ? b.bp - a.bp : a.bp - b.bp) : 0) || a.first - b.first)
    for (let i = 1; i < strand.length; i++) addEdge(strand[i - 1].site, strand[i].site)
  }
  // Geometry without strand metadata still gets its axial backbone.
  if (!byStrand.size) {
    const byHelix = new Map()
    ordered.forEach((site, index) => {
      const entries = byHelix.get(site.helix) ?? []
      entries.push({ index, bp: site.bp })
      byHelix.set(site.helix, entries)
    })
    for (const entries of byHelix.values()) {
      entries.sort((a, b) => a.bp - b.bp)
      for (let i = 1; i < entries.length; i++) addEdge(entries[i - 1].index, entries[i].index)
    }
  }
  return { points, edges: [...edgeKeys].map(key => key.split(':').map(Number)) }
}
