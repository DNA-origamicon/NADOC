import { junctionIndex } from '../design/strand_junctions.js'
import { domainKeys, strandSequenceDisplay, renderStrandSequence } from './strand_sequence_display.js'
import { baseKey, xbKey } from '../scene/base_ref.js'

/** Project logical selections onto sequence identities without changing the design. */
export function selectedSequenceKeys(design, refs = []) {
  refs = refs.filter(ref => ['base', 'end', 'bond', 'domain', 'overhang', 'crossover'].includes(ref.kind))
  if (!refs.length) return new Map()
  const keys = new Set()
  const add = values => values.forEach(key => keys.add(key))
  for (const ref of refs) {
    if (ref.kind === 'base' || ref.kind === 'end') keys.add(ref.key)
    if (ref.kind === 'bond') add([ref.fromKey, ref.toKey])
    if (ref.kind === 'crossover') {
      const forced = ref.subtype === 'forced_ligation'
      const j = (forced ? design?.forced_ligations : design?.crossovers)?.find(j => j.id === ref.id)
      if (!j) continue
      const halves = forced ? [
        { helix_id: j.three_prime_helix_id, index: j.three_prime_bp, strand: j.three_prime_direction },
        { helix_id: j.five_prime_helix_id, index: j.five_prime_bp, strand: j.five_prime_direction },
      ] : [j.half_a, j.half_b]
      add(halves.map(h => baseKey({ helix_id: h.helix_id, bp_index: h.index, direction: h.strand })))
      add([...(j.extra_bases ?? '')].map((_, i) => xbKey(j.id, i)))
    }
  }
  const out = new Map()
  const index = junctionIndex(design)
  for (const strand of design?.strands ?? []) {
    const owned = (strand.domains ?? []).flatMap(d => domainKeys(d, design))
    owned.push(...strandSequenceDisplay(strand, design, undefined, index).runs.flatMap(r => r.keys))
    const selected = new Set(owned.filter(key => keys.has(key)))
    strand.domains?.forEach((d, i) => {
      if (refs.some(r => (r.kind === 'domain' && r.strandId === strand.id && r.domainIndex === i)
        || (r.kind === 'overhang' && r.id === d.overhang_id))) {
        domainKeys(d, design).forEach(key => selected.add(key))
      }
    })
    if (selected.size) out.set(strand.id, selected)
  }
  return out
}

/** A selectable readout beside the existing overhang editor; editing stays intact. */
export function highlightOverhangCell(cell, domain, design, selected = new Set()) {
  if (domain?.overhang_id == null) return
  const keys = domainKeys(domain, design)
  if (!keys.some(key => selected.has(key))) return
  const input = cell.querySelector('input')
  const preview = document.createElement('span')
  preview.className = 'sheet-seq sheet-search-text sheet-overhang-selection'
  preview.title = 'Selected overhang bases; edit sequence below'
  const refresh = () => {
    const text = (input?.value || '').padEnd(keys.length, 'N').slice(0, keys.length)
    preview.replaceChildren()
    renderStrandSequence(preview, { runs: [{ text, keys }] }, selected)
  }
  refresh()
  input?.addEventListener('input', refresh)
  cell.prepend(preview)
}
