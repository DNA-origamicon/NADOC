import { parseBaseKey } from './base_ref.js'
import { baseKey } from './base_ref.js'
import { buildNucLetterMap } from './helix_renderer/palette.js'

export function canConvertThymines(design, keys, geometry = []) {
  if (keys.length !== 2 || new Set(keys).size !== 2) return false
  const consumed = new Set((design?.photoproduct_junctions ?? []).flatMap(p => [p.base_key_1, p.base_key_2, ...Object.keys(p.context_coordinates ?? {})]))
  const owners = [...(design?.crossovers ?? []), ...(design?.forced_ligations ?? [])]
  const letters = new Map([...buildNucLetterMap(design, geometry)].map(([n, letter]) => [baseKey(n, n.copy ?? n.copy_k ?? 0), letter]))
  return keys.every(key => {
    const p = parseBaseKey(key)
    if (!p || consumed.has(key)) return false
    return p.helix_id === '__xb__'
      ? owners.find(o => o.id === p.crossover_id)?.extra_bases?.[p.k]?.toUpperCase() === 'T'
      : !p.helix_id.startsWith('__') && letters.get(key) === 'T'
  })
}

export function cpdSelectionKeys(state) {
  const owners = [...(state.currentDesign?.crossovers ?? []), ...(state.currentDesign?.forced_ligations ?? [])]
  const keys = []
  for (const ref of state.selection?.items ?? []) {
    if (ref.kind === 'base') keys.push(ref.key)
    else if (ref.kind === 'crossover') {
      const owner = owners.find(o => o.id === ref.id)
      for (let k = 0; k < (owner?.extra_bases?.length ?? 0); k++) keys.push(`__xb__:${owner.id}:${k}`)
    } else return []
  }
  return [...new Set(keys)]
}

export function canConvertExtraThymines(design, keys) {
  if (keys.length !== 2 || new Set(keys).size !== 2) return false
  const consumed = new Set((design?.photoproduct_junctions ?? []).flatMap(p => [p.base_key_1, p.base_key_2, ...Object.keys(p.context_coordinates ?? {})]))
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
