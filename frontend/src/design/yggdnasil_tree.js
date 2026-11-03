/** A fixed-length slice of the atlas. Edges change radius only, by one shell.
 * Routing filters remove vertices/edges; they never rewire around missing nodes.
 */
import { routingScreen } from './yggdnasil_routing.js'
export function buildYggTree(atlas, { length = 100, filter = 'all' } = {}) {
  const nodes = [], edges = [], stems = []
  const show = entry => {
    const r = routingScreen(entry)
    return filter === 'all' || (filter === 'remaining' && !r.excluded) ||
      (filter === 'excluded' && r.excluded) || (filter === 'unresolved' && r.status === 'unresolved')
  }
  for (const [li, lattice] of ['square', 'honeycomb'].entries()) {
    const sign = li ? 1 : -1
    for (const [ci, center] of ['Helix', 'Bond', 'Cell'].entries()) {
      const family = atlas.entries.filter(e => e.lattice === lattice && e.minLength <= length && e.maxLength >= length && e.sources.some(s => s.center === center))
        .sort((a, b) => a.sources.find(s => s.center === center).radiusNm - b.sources.find(s => s.center === center).radiusNm)
      const chain = family.map((entry, i) => {
        const t = family.length > 1 ? i / (family.length - 1) : 0
        return { id: `${entry.id}:${center}`, entry, center, lattice, length,
          radiusNm: entry.sources.find(s => s.center === center).radiusNm,
          index: i, position: [sign * (7 + 16 * t + ci * 2.8), 3 + 27 * t + ci * 1.4, (ci - 1) * 9 + Math.sin(t * Math.PI) * 3],
          visible: show(entry), routing: routingScreen(entry) }
      })
      nodes.push(...chain.filter(n => n.visible))
      if (chain[0]?.visible) stems.push({ to: chain[0].id, lattice })
      for (let i = 1; i < chain.length; i++) {
        const a = chain[i - 1], b = chain[i]
        if (a.visible && b.visible) edges.push({ from: a.id, to: b.id, deltaHelices: b.entry.helices - a.entry.helices, parameter: 'radius', center, lattice, length })
      }
    }
  }
  return { nodes, edges, stems, length, filter, structureCount: new Set(nodes.map(n => n.entry.id)).size }
}
