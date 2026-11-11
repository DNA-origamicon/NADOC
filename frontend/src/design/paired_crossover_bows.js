/** Schematic bow classes from unique adjacent reciprocal strand transitions.
 * Left/right is along the BP axis, not a world-space molecular displacement.
 */
import { junctionIndex, strandJunctions } from './strand_junctions.js'

export function pairedCrossoverBows(design) {
  const index = junctionIndex(design), groups = new Map()
  for (const strand of design?.strands ?? []) {
    const domains = strand.domains ?? [], junctions = strandJunctions(strand, index)
    for (let i = 0; i + 1 < domains.length; i++) {
      const a = domains[i], b = domains[i + 1], junction = junctions[i]
      if (!junction || junction.is_periodic_seam || a.helix_id === b.helix_id) continue
      const helices = [a.helix_id, b.helix_id].sort()
      const key = JSON.stringify(helices)
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push({ id: junction.id, source: a.helix_id,
        sites: new Map([[a.helix_id, [a.end_bp, a.direction]],
          [b.helix_id, [b.start_bp, b.direction]]]) })
    }
  }
  const bows = new Map()
  for (const connectors of groups.values()) {
    const partners = connectors.map(() => [])
    for (let i = 0; i < connectors.length; i++) {
      for (let j = i + 1; j < connectors.length; j++) {
        const a = connectors[i], b = connectors[j]
        if (a.id === b.id || a.source === b.source) continue
        const deltas = [...a.sites].map(([helix, [bp, direction]]) => {
          const other = b.sites.get(helix)
          return other?.[1] === direction ? other[0] - bp : NaN
        })
        if (Math.abs(deltas[0]) !== 1 || deltas[0] !== deltas[1]) continue
        partners[i].push([j, -Math.sign(deltas[0])])
        partners[j].push([i, Math.sign(deltas[0])])
      }
    }
    for (let i = 0; i < connectors.length; i++) {
      if (partners[i].length !== 1) continue
      const [j, bow] = partners[i][0]
      if (partners[j].length === 1) bows.set(connectors[i].id, bow)
    }
  }
  return bows
}
