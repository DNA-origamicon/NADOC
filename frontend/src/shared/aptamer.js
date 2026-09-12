/** Authored pairing selects geometry; source coordinates remain available. */
export function nativeCorePaired(helix, design) {
  if (!helix.native_residues?.length) return false
  const core = new Set(helix.native_residues.map(site => site.bp_index))
  const occupied = { FORWARD: new Set(), REVERSE: new Set() }
  for (const strand of design.strands ?? []) {
    if (strand.is_reference) continue
    for (const domain of strand.domains ?? []) {
      if (domain.helix_id !== helix.id) continue
      const lo = Math.min(domain.start_bp, domain.end_bp)
      const hi = Math.max(domain.start_bp, domain.end_bp)
      for (const bp of core) if (lo <= bp && bp <= hi) occupied[domain.direction]?.add(bp)
    }
  }
  return [...occupied.FORWARD].some(bp => occupied.REVERSE.has(bp))
}

export function quadruplexMarkers(design) {
  const markers = []
  for (const helix of design?.helices ?? []) {
    if (!helix.native_residues?.length) continue
    const core = helix.native_residues.map(s => s.bp_index)
    const lo = Math.min(...core), hi = Math.max(...core)
    const owner = (design.strands ?? []).find(s => !s.is_reference && s.domains.some(d =>
      d.helix_id === helix.id && d.direction === 'FORWARD' &&
      Math.min(d.start_bp, d.end_bp) <= hi && Math.max(d.start_bp, d.end_bp) >= lo))
    if (owner) markers.push({ helixId: helix.id, strandId: owner.id, bp: (lo + hi) / 2,
      paired: nativeCorePaired(helix, design) })
  }
  return markers
}
