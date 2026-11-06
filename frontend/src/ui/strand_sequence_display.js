import { baseKey, xbKey, parseBaseKey } from '../scene/base_ref.js'
import { junctionIndex, strandJunctions, domainJunctions } from '../design/strand_junctions.js'

/** Sequence positions in 5′→3′ order, including loop copies and excluding skips. */
export function domainKeys(domain, design) {
  const helix = design?.helices?.find(h => h.id === domain.helix_id)
  const deltas = new Map((helix?.loop_skips ?? []).map(ls => [ls.bp_index, ls.delta]))
  const keys = []
  const step = domain.end_bp >= domain.start_bp ? 1 : -1
  for (let bp = domain.start_bp; ; bp += step) {
    const delta = domain.overhang_id != null || domain.binds_overhang_id != null ? 0 : (deltas.get(bp) ?? 0)
    for (let copy = 0; copy < 1 + delta; copy++) {
      keys.push(baseKey({ helix_id: domain.helix_id, bp_index: bp, direction: domain.direction }, copy))
    }
    if (bp === domain.end_bp) break
  }
  return keys
}

export function strandLength(strand, design, index = junctionIndex(design)) {
  const junctions = strandJunctions(strand, index)
  return (strand.domains ?? []).reduce((n, d, i) =>
    n + domainKeys(d, design).length + (junctions[i]?.extra_bases?.length ?? 0)
      + [...domainJunctions(d, index).values()].reduce((sum, j) => sum + (j.extra_bases?.length ?? 0), 0), 0)
}

const RC = { A: 'T', T: 'A', G: 'C', C: 'G', N: 'N' }
function liveBinderSequence(strand, design) {
  let any = false
  const chunks = strand.domains.map(d => {
    const len = Math.abs(d.end_bp - d.start_bp) + 1
    const spec = design?.overhangs?.find(o => o.id === d.binds_overhang_id)
    if (!spec?.sequence) return 'N'.repeat(len)
    any = true
    return [...spec.sequence.slice(0, len).padEnd(len, 'N')].reverse().map(c => RC[c.toUpperCase()] ?? 'N').join('')
  })
  return any ? chunks.join('') : null
}

function extensionText(ext) {
  const seq = (ext.sequence ?? '').toUpperCase()
  const mod = (ext.modification ?? '').toUpperCase()
  return `[${seq}${mod || !seq ? '/' + mod : ''}]`
}

/** Text and base identities share one projection, so arcs and selection never
 * change copied/searchable sequence or shift the downstream base highlights.
 * Terminal overhang columns and terminal extension notation retain their roles.
 */
export function strandSequenceDisplay(strand, design, selectedKeys = new Set(), index = junctionIndex(design)) {
  const domains = strand.domains ?? []
  const junctions = strandJunctions(strand, index)
  const internal = domains.map(d => domainJunctions(d, index))
  const ext5 = design?.extensions?.find(e => e.strand_id === strand.id && e.end === 'five_prime')
  const ext3 = design?.extensions?.find(e => e.strand_id === strand.id && e.end === 'three_prime')
  let seq = strand.sequence
  if (!seq && domains.some(d => d.binds_overhang_id)) seq = liveBinderSequence(strand, design)
  const hasInsert = [...junctions, ...internal.flatMap(m => [...m.values()])].some(j => j?.extra_bases)
  const runs = []
  const insert = junction => {
    if (junction?.extra_bases) runs.push({ text: junction.extra_bases, junctionId: junction.id,
      keys: [...junction.extra_bases].map((_, k) => xbKey(junction.id, k)) })
  }
  if (ext5) runs.push({ text: extensionText(ext5), keys: [] })
  let offset = 0
  domains.forEach((d, i) => {
    const keys = domainKeys(d, design)
    const text = seq ? seq.slice(offset, offset + keys.length) : (hasInsert || selectedKeys.size ? 'N'.repeat(keys.length) : '')
    offset += keys.length
    const terminalOverhang = d.overhang_id != null && (i === 0 || i === domains.length - 1)
    if (!terminalOverhang) {
      let start = 0
      for (let k = 0; k < keys.length && internal[i].size; k++) {
        const bp = parseBaseKey(keys[k]).bp_index
        if (!internal[i].has(bp) || parseBaseKey(keys[k + 1])?.bp_index === bp) continue
        runs.push({ text: text.slice(start, k + 1), keys: keys.slice(start, k + 1) })
        insert(internal[i].get(bp))
        start = k + 1
      }
      runs.push({ text: text.slice(start), keys: keys.slice(start) })
    }
    insert(junctions[i])
  })
  if (ext3) runs.push({ text: extensionText(ext3), keys: [] })
  return { text: runs.map(r => r.text).join(''), runs }
}

export function renderStrandSequence(container, display, selectedKeys = new Set()) {
  for (const run of display.runs) {
    let parent = container
    if (run.junctionId != null) {
      parent = document.createElement('span')
      parent.className = 'sheet-seq-extra'
      parent.title = 'Extra crossover bases'
      container.appendChild(parent)
    }
    // Keep contiguous unselected sequence in one text node. A scaffold can have
    // thousands of bases; one DOM node per base makes selection-triggered layout costly.
    let start = 0
    for (let i = 0; i < run.text.length; i++) {
      if (selectedKeys.has(run.keys[i])) {
        if (i > start) parent.appendChild(document.createTextNode(run.text.slice(start, i)))
        const mark = document.createElement('mark')
        mark.className = 'sheet-seq-selected-base'
        mark.textContent = run.text[i]
        parent.appendChild(mark)
        start = i + 1
      }
    }
    if (start < run.text.length) parent.appendChild(document.createTextNode(run.text.slice(start)))
  }
}
