/** Renderer-level molecular audit helpers. Read live entry positions, not topology files,
 * so diagnostics describe exactly what Three.js is drawing after RMSF/trajectory overlays. */

const _origin = (n = {}) => ({
  helix_id: n.helix_id ?? null,
  bp_index: n.bp_index ?? null,
  direction: n.direction ?? null,
  strand_id: n.strand_id ?? null,
  strand_type: n.strand_type ?? null,
  domain_index: n.domain_index ?? null,
  is_surface_capture: !!n.is_surface_capture,
})

const _xyz = (entry) => {
  const p = entry?.pos ?? entry?.nuc?.backbone_position
  if (!p) return null
  if (Array.isArray(p)) return p.slice(0, 3).map(Number)
  return [Number(p.x), Number(p.y), Number(p.z)]
}

export function auditRenderedBonds(backboneEntries = [], coneEntries = [], thresholdNm = 2,
                                   renderedLength = null) {
  const pos = new Map(backboneEntries.map(e => [e.nuc, _xyz(e)]))
  const bonds = []
  for (const cone of coneEntries) {
    const from = pos.get(cone.fromNuc) ?? _xyz({ nuc: cone.fromNuc })
    const to = pos.get(cone.toNuc) ?? _xyz({ nuc: cone.toNuc })
    if (!from || !to || [...from, ...to].some(v => !Number.isFinite(v))) continue
    const length_nm = Math.hypot(to[0] - from[0], to[1] - from[1], to[2] - from[2])
    const matrix_length_nm = Number(renderedLength?.(cone))
    const drawnLength = Number.isFinite(matrix_length_nm) ? matrix_length_nm : length_nm
    bonds.push({
      render_kind: cone.isCrossHelix ? 'cross_helix_arc' : 'backbone_cone',
      length_nm,
      matrix_length_nm: drawnLength,
      endpoint_matrix_delta_nm: Math.abs(drawnLength - length_nm),
      over_threshold: drawnLength > thresholdNm,
      strand_id: cone.strandId ?? cone.fromNuc?.strand_id ?? null,
      from: { ..._origin(cone.fromNuc), position: from },
      to: { ..._origin(cone.toNuc), position: to },
    })
  }
  bonds.sort((a, b) => b.matrix_length_nm - a.matrix_length_nm)
  return {
    threshold_nm: thresholdNm,
    n_bonds: bonds.length,
    n_over_threshold: bonds.filter(b => b.over_threshold).length,
    max_length_nm: bonds[0]?.matrix_length_nm ?? null,
    over_threshold: bonds.filter(b => b.over_threshold),
    bonds,
  }
}

export function inventoryRenderedElements(backboneEntries = [], slabEntries = [], coneEntries = []) {
  const count = (xs, f) => xs.filter(f).length
  const cap = e => !!(e?.nuc?.is_surface_capture ?? e?.fromNuc?.is_surface_capture)
  return {
    beads: backboneEntries.length,
    slabs: slabEntries.length,
    bonds: coneEntries.length,
    surface_capture_beads: count(backboneEntries, cap),
    surface_capture_slabs: count(slabEntries, cap),
    surface_capture_bonds: count(coneEntries, cap),
    cross_helix_bonds: count(coneEntries, e => !!e.isCrossHelix),
    strand_ids: [...new Set(backboneEntries.map(e => e.nuc?.strand_id).filter(Boolean))].sort(),
  }
}
