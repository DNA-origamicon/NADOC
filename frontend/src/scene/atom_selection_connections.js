import { parseBaseKey, xbKey } from './base_ref.js'

export const atomSelectionBondKey = (a, b) => JSON.stringify([a, b].sort())

/** Connection records own endpoints; selection never infers molecular connectivity. */
export function atomSelectionConnections(highlight, design) {
  const bonds = (highlight.bonds ?? []).map(({ fromKey, toKey }) => [fromKey, toKey])
  const bases = []
  for (const ref of highlight.crossovers ?? []) {
    const forced = ref.subtype === 'forced_ligation'
    const connection = (forced ? design?.forced_ligations : design?.crossovers)?.find(c => c.id === ref.id)
    if (!connection) continue
    const halves = forced ? [
      { helix_id: connection.three_prime_helix_id, index: connection.three_prime_bp, strand: connection.three_prime_direction },
      { helix_id: connection.five_prime_helix_id, index: connection.five_prime_bp, strand: connection.five_prime_direction },
    ] : [connection.half_a, connection.half_b]
    const endpoints = halves.map(h => h && `${h.helix_id}:${h.index}:${h.strand}`)
    if (!endpoints.every(key => parseBaseKey(key))) continue
    const inserts = Array.from({ length: connection.extra_bases?.length ?? 0 }, (_, k) => xbKey(connection.id, k))
    bases.push(...inserts.map(parseBaseKey))
    const path = [endpoints[0], ...inserts, endpoints[1]]
    for (let i = 1; i < path.length; i++) bonds.push([path[i - 1], path[i]])
  }
  return { bases, bonds }
}
