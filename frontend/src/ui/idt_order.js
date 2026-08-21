/** Build stable, unique IDT oligo names in physical plate/well order. */
export function buildIdtStrandNames(design, strandGroups = [], layout = design?.plate_layout) {
  const groupNameByStrand = new Map()
  for (const group of strandGroups ?? []) {
    const name = String(group?.name ?? '').trim()
    if (!name) continue
    for (const strandId of group.strandIds ?? group.strand_ids ?? []) {
      if (!groupNameByStrand.has(strandId)) groupNameByStrand.set(strandId, name)
    }
  }

  // An overhang name takes precedence over the ordinary strand group name.
  const overhangNameByStrand = new Map()
  for (const overhang of design?.overhangs ?? []) {
    const name = String(overhang?.label || overhang?.name || overhang?.id || '').trim()
    if (name && !overhangNameByStrand.has(overhang.strand_id)) {
      overhangNameByStrand.set(overhang.strand_id, name)
    }
  }

  const counters = new Map()
  const names = {}
  const staples = (design?.strands ?? []).filter(
    strand => strand.strand_type === 'staple' && !strand.is_reference,
  )
  const stapleById = new Map(staples.map(strand => [strand.id, strand]))
  const orderedIds = []
  const seen = new Set()
  const add = id => {
    if (!seen.has(id) && stapleById.has(id)) { seen.add(id); orderedIds.push(id) }
  }
  // Physical IDT order: Plate 1 A1→H12, then Plate 2, and so on.
  ;[...(layout?.wells ?? [])]
    .sort((a, b) => (a.plate - b.plate) || (a.row - b.row) || (a.col - b.col))
    .forEach(well => add(well.strand_id))
  ;(layout?.tubes ?? []).forEach(tube => add(tube.strand_id))
  staples.forEach(strand => add(strand.id))

  let stapleNumber = 0
  for (const strandId of orderedIds) {
    const strand = stapleById.get(strandId)
    stapleNumber += 1
    const base = overhangNameByStrand.get(strand.id) || groupNameByStrand.get(strand.id)
    if (!base) {
      names[strand.id] = `S${stapleNumber}`
      continue
    }
    const next = (counters.get(base) ?? 0) + 1
    counters.set(base, next)
    names[strand.id] = `${base}_${next}`
  }
  return names
}
