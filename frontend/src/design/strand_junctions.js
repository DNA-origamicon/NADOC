// Junction ownership follows the ordered strand path, independent of how a
// crossover's two halves are stored. Forced ligations are explicitly 3′→5′.
const endpoint = (helix, bp, direction) => JSON.stringify([helix, bp, direction])
const pair = (a, b) => `${a}|${b}`
const axis = half => JSON.stringify([half.helix_id, half.strand])

export function junctionIndex(design) {
  const byPair = new Map(), internal = new Map()
  function add(a, b, junction) {
    byPair.set(pair(endpoint(a.helix_id, a.index, a.strand), endpoint(b.helix_id, b.index, b.strand)), junction)
    if (axis(a) !== axis(b) || Math.abs(a.index - b.index) !== 1) return
    const key = axis(a)
    if (!internal.has(key)) internal.set(key, [])
    internal.get(key).push({ a, b, junction })
  }
  for (const xo of design?.crossovers ?? []) {
    add(xo.half_a, xo.half_b, xo)
    add(xo.half_b, xo.half_a, xo)
  }
  for (const fl of design?.forced_ligations ?? []) {
    add({ helix_id: fl.three_prime_helix_id, index: fl.three_prime_bp, strand: fl.three_prime_direction },
      { helix_id: fl.five_prime_helix_id, index: fl.five_prime_bp, strand: fl.five_prime_direction }, fl)
  }
  return { byPair, internal }
}

/** One junction after each domain (null where no connection exists). */
export function strandJunctions(strand, index) {
  const domains = strand.domains ?? []
  return domains.map((d, i) => {
    const next = domains[i + 1] ?? domains[0]
    if (!next || d.overhang_id != null || next.overhang_id != null) return null
    return index.byPair.get(pair(endpoint(d.helix_id, d.end_bp, d.direction),
      endpoint(next.helix_id, next.start_bp, next.direction))) ?? null
  })
}

/** Native ligation merges adjacent same-helix domains; its connection record
 * still owns any inserted bases at that internal backbone edge. */
export function domainJunctions(domain, index) {
  const out = new Map()
  if (domain.overhang_id != null) return out
  const step = domain.end_bp >= domain.start_bp ? 1 : -1
  const lo = Math.min(domain.start_bp, domain.end_bp), hi = Math.max(domain.start_bp, domain.end_bp)
  for (const { a, b, junction } of index.internal.get(axis({ helix_id: domain.helix_id, strand: domain.direction })) ?? []) {
    if (b.index === a.index + step && a.index >= lo && a.index <= hi && b.index >= lo && b.index <= hi) {
      out.set(a.index, junction)
    }
  }
  return out
}

export function extraBaseOwners(design) {
  const index = junctionIndex(design)
  const owners = new Map()
  for (const strand of design?.strands ?? []) {
    const junctions = [...strandJunctions(strand, index),
      ...(strand.domains ?? []).flatMap(d => [...domainJunctions(d, index).values()])]
    for (const junction of junctions) {
      if (junction?.extra_bases) owners.set(junction.id, strand)
    }
  }
  return owners
}
