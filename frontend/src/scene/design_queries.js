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

// Returns {strand_id, domain_index} for every domain in the design that BINDS the
// given overhang (Domain.binds_overhang_id === ovhgId) — strand-type-agnostic, so it
// covers standalone OH_BINDER strands, LINKER complements, AND end-to-root binders
// spliced into a STAPLE strand. Used so the orientation-edit live preview rotates the
// binder (and any toehold extending past the overhang on the same helix) with the
// overhang. The per-overhang filter keeps OTHER overhangs' binders out.
export function ovhgBinderDomainIds(ovhgId, design) {
  if (!ovhgId) return []
  const out = []
  for (const s of design?.strands ?? []) {
    s.domains?.forEach((d, i) => {
      if (d.binds_overhang_id === ovhgId) out.push({ strand_id: s.id, domain_index: i })
    })
  }
  return out
}

/** Geometry key "helix:bp:dir" for a flexible-connection anchor, or null. */
export function flexAnchorKey(anc, design) {
  const s = design?.strands?.find(s => s.id === anc.strand_id)
  const d = s?.domains?.[anc.domain_index]
  return d ? `${d.helix_id}:${anc.bp_index}:${anc.direction}` : null
}

/**
 * Flexible ssDNA segments: the contiguous run of UNPAIRED beads containing the
 * clicked bead, within its strand (5'→3' order). Returns a list of mark bodies
 * {strand_id, domain_index, bp_index, direction}. Falls back to the single bead
 * if the run can't be resolved. Used to mark/unmark a whole tether at once.
 * `geometry` is the per-nucleotide list carrying `is_unpaired`.
 */
export function flexibleRunForBead(design, geometry, nuc) {
  const single = [{ strand_id: nuc.strand_id, domain_index: nuc.domain_index,
                    bp_index: nuc.bp_index, direction: nuc.direction }]
  const strand = design?.strands?.find(s => s.id === nuc.strand_id)
  if (!strand) return single
  // Build the strand's 5'→3' bead order with (domain_index, helix, bp, direction).
  const order = []
  strand.domains.forEach((d, di) => {
    const step = d.end_bp >= d.start_bp ? 1 : -1
    for (let bp = d.start_bp; ; bp += step) {
      order.push({ helix_id: d.helix_id, bp, direction: d.direction, domain_index: di })
      if (bp === d.end_bp) break
    }
  })
  const k = o => `${o.helix_id}:${o.bp}:${o.direction}`
  const unpaired = new Set((geometry ?? [])
    .filter(n => n.is_unpaired)
    .map(n => `${n.helix_id}:${n.bp_index}:${n.direction}`))
  const idx = order.findIndex(o =>
    o.helix_id === nuc.helix_id && o.bp === nuc.bp_index && o.direction === nuc.direction)
  if (idx < 0 || !unpaired.has(k(order[idx]))) return single
  let lo = idx, hi = idx
  while (lo - 1 >= 0 && unpaired.has(k(order[lo - 1]))) lo--
  while (hi + 1 < order.length && unpaired.has(k(order[hi + 1]))) hi++
  return order.slice(lo, hi + 1).map(o => ({
    strand_id: nuc.strand_id, domain_index: o.domain_index,
    bp_index: o.bp, direction: o.direction,
  }))
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
