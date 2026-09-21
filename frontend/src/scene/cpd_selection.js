import { parseBaseKey } from './base_ref.js'

export function canConvertExtraThymines(design, keys) {
  if (keys.length !== 2 || new Set(keys).size !== 2) return false
  const consumed = new Set((design?.photoproduct_junctions ?? []).flatMap(p => [p.base_key_1, p.base_key_2]))
  const owners = [...(design?.crossovers ?? []), ...(design?.forced_ligations ?? [])]
  return keys.every(key => {
    const p = parseBaseKey(key)
    return p?.helix_id === '__xb__' && !consumed.has(key) &&
      owners.find(o => o.id === p.crossover_id)?.extra_bases?.[p.k]?.toUpperCase() === 'T'
  })
}

/** A converted CPD is indivisible at Base and Crossover selection levels. */
export function expandCpdTargets(design, keys, refs = []) {
  const result = new Set(keys)
  const crossovers = new Set(refs.filter(r => r.kind === 'crossover').map(r => r.id))
  for (const p of design?.photoproduct_junctions ?? []) {
    if (!Object.keys(p.design_coordinates ?? {}).length) continue
    const pair = [p.base_key_1, p.base_key_2]
    if (pair.some(k => result.has(k) || crossovers.has(parseBaseKey(k)?.crossover_id))) {
      pair.forEach(k => result.add(k))
    }
  }
  return [...result]
}
