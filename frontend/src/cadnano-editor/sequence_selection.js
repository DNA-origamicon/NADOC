import { domainLineKey, domainEndKey, xoverKey, forcedLigKey, parseEndKey } from './element_keys.js'
import { baseKey } from '../scene/base_ref.js'

/** Translate the editor's element identities without expanding to whole strands. */
export function sequenceSelectionRefs(design, elements) {
  const refs = []
  for (const strand of design?.strands ?? []) strand.domains?.forEach((d, domainIndex) => {
    if (elements.has(domainLineKey(d))) refs.push({ kind: 'domain', strandId: strand.id, domainIndex })
    for (const end of ['5p', '3p']) {
      const key = domainEndKey(d, end)
      if (!elements.has(key)) continue
      const parsed = parseEndKey(key)
      refs.push({ kind: 'base', key: baseKey({ ...parsed, bp_index: parsed.bp }) })
    }
  })
  for (const j of design?.crossovers ?? []) if (elements.has(xoverKey(j))) refs.push({ kind: 'crossover', id: j.id })
  for (const j of design?.forced_ligations ?? []) if (elements.has(forcedLigKey(j))) refs.push({ kind: 'crossover', id: j.id, subtype: 'forced_ligation' })
  return refs
}
