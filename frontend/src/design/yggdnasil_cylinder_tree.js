import { routingScreen } from './yggdnasil_routing.js'

/** Inner-radius steps at fixed outer radius. Stems are taxonomy, not transitions. */
export function buildCylinderTree(atlas, { filter = 'all' } = {}) {
  const nodes = [], edges = [], stems = [], families = new Map()
  for (const entry of atlas.entries) for (const source of entry.sources) {
    const key = `${entry.lattice}:${source.center}:${source.outerShell}`
    if (!families.has(key)) families.set(key, [])
    families.get(key).push({ entry, source })
  }
  const maxRadius = Math.max(1, ...atlas.entries.flatMap(e => e.sources.map(s => s.outerRadiusNm)))
  for (const [family, candidates] of families) {
    candidates.sort((a, b) => a.source.innerShell - b.source.innerShell)
    let previous = null, rootId = null
    for (const { entry, source } of candidates) {
      const routing = routingScreen(entry)
      if (routing.excluded || filter === 'excluded' || (filter === 'unresolved' && routing.status !== 'unresolved')) { previous = null; continue }
      const sign = entry.lattice === 'square' ? -1 : 1
      const ci = ['Helix', 'Bond', 'Cell'].indexOf(source.center)
      const outer = source.outerRadiusNm / maxRadius, inner = source.innerRadiusNm / Math.max(source.outerRadiusNm, 1)
      const id = `hollow:${source.key}`, node = { id, entry, source, center: source.center, lattice: entry.lattice,
        shape: 'hollow', length: atlas.length, routing, index: source.shellIndex, family,
        outerRadiusNm: source.outerRadiusNm, innerRadiusNm: source.innerRadiusNm,
        label: `${entry.helices}hb ○`,
        position: [sign * (8 + 17 * outer + ci * 2 + 12 * inner), 3 + 27 * outer - 5 * inner, 23 + (ci - 1) * 7 + 7 * inner] }
      rootId ??= id; node.rootId = rootId
      if (id === rootId) stems.push({ to: id, lattice: entry.lattice, shape: 'hollow' })
      nodes.push(node)
      if (previous && node.index === previous.index + 1) edges.push({ from: previous.id, to: id,
        parameter: 'inner-radius', lattice: entry.lattice, center: node.center, length: atlas.length,
        outerRadiusNm: source.outerRadiusNm, deltaHelices: entry.helices - previous.entry.helices,
        label: `ΔRi ${(node.innerRadiusNm - previous.innerRadiusNm).toFixed(2)} nm` })
      previous = node
    }
  }
  return { nodes, edges, stems, length: atlas.length, filter, structureCount: new Set(nodes.map(n => n.entry.id)).size }
}
