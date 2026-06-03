/**
 * Pure design-graph lookups extracted from main.js — operate on a plain `design`
 * object (overhangs / strands / domains / representation_overrides /
 * flexible_connections) with no scene/store/renderer access. Unit-tested in
 * design_queries.test.js.
 */

/** Flatten representation_overrides to the list of 'surface'-rep segments. */
export function surfaceSegments(design) {
  const segs = []
  for (const ov of design?.representation_overrides ?? []) {
    if (ov.representation === 'surface') for (const s of ov.segments ?? []) segs.push(s)
  }
  return segs
}

/** True if the overhang lives on its own helix (no scaffold domain on it) — i.e.
 *  an extrude-style overhang rather than an inline one. */
export function isExtrudeOverhang(ovhgId, design) {
  const o = design?.overhangs?.find(x => x.id === ovhgId)
  if (!o?.helix_id) return false
  return !design?.strands?.some(
    s => s.strand_type === 'scaffold' && s.domains?.some(d => d.helix_id === o.helix_id)
  )
}

// Returns domain ID objects for the overhang's strand — used to filter captureClusterBase
// and applyClusterTransform so that unselected overhangs sharing the same child helix are
// not affected by the live preview transform.
export function ovhgDomainIds(ovhgId, design) {
  const o = design?.overhangs?.find(x => x.id === ovhgId)
  if (!o) return null
  const strand = design?.strands?.find(s => s.id === o.strand_id)
  if (!strand?.domains?.length) return null
  return strand.domains.map((_, i) => ({ strand_id: strand.id, domain_index: i }))
}

/** Geometry key "helix:bp:dir" for a flexible-connection anchor, or null. */
export function flexAnchorKey(anc, design) {
  const s = design?.strands?.find(s => s.id === anc.strand_id)
  const d = s?.domains?.[anc.domain_index]
  return d ? `${d.helix_id}:${anc.bp_index}:${anc.direction}` : null
}

/** Find the flexible connection whose marked run contains this bead, or null. */
export function connIdForBead(nuc, design) {
  for (const c of (design?.flexible_connections ?? [])) {
    for (const k of (c.segment_bead_keys ?? [])) {
      if (k.strand_id === nuc.strand_id && k.domain_index === nuc.domain_index &&
          k.bp_index === nuc.bp_index && k.direction === nuc.direction) return c.id
    }
  }
  return null
}
