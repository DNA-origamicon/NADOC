import { baseKey } from './base_ref.js'
import { coloringFallbackMode, nextColoringMode, supportedColoringSet } from './coloring_modes.js'

export function strandDisplayOverrides(design) {
  const result = new Map()
  for (const row of design?.representation_overrides ?? []) {
    for (const id of row.strand_ids ?? []) result.set(id, row)
  }
  return result
}

/** Keep strand ownership independent of duplex/domain column overrides. */
export function editStrandRepresentation(design, ids, representation, { cycle = false, globalRepresentation = 'full', globalColoring = 'strand' } = {}) {
  const selected = new Set(ids), current = strandDisplayOverrides(design)
  const repeat = cycle && ids.every(id => (current.get(id)?.representation ?? globalRepresentation) === representation)
  const rows = (design.representation_overrides ?? []).map(row => ({
    ...row, strand_ids: (row.strand_ids ?? []).filter(id => !selected.has(id)),
  })).filter(row => row.segments?.length || row.protein_attachment_ids?.length || row.strand_ids.length)
  for (const id of selected) {
    const previous = current.get(id)?.coloring ?? globalColoring
    const coloring = repeat
      ? nextColoringMode([...supportedColoringSet(representation)], previous) ?? previous
      : coloringFallbackMode(representation, previous) ?? previous
    rows.push({ strand_ids: [id], segments: [], representation, coloring })
  }
  return rows
}

/** Reuse independently colored display layers with exact nucleotide membership. */
export function strandRepresentationLayers(state) {
  const rows = strandDisplayOverrides(state.currentDesign), members = new Map()
  for (const n of state.currentGeometry ?? []) {
    if (!rows.has(n.strand_id)) continue
    if (!members.has(n.strand_id)) members.set(n.strand_id, [])
    members.get(n.strand_id).push(n)
  }
  return [...members].map(([id, nucleotides]) => {
    const row = rows.get(id)
    return { id: `strand:${id}`, strandId: id, representation: row.representation,
      coloring: row.coloring ?? 'strand', opacity: 1,
      keys: [...new Set(nucleotides.map(n => `${n.helix_id}:${n.bp_index}`))],
      baseKeys: nucleotides.map(n => baseKey(n, n.copy_k ?? 0)), segments: [],
    }
  })
}
