// Ordinary backbone bonds may span helix records when Sweep extends a blunt end.
// Mirror backend/core/backbone_continuations.py: authored strand order and sweep
// attachment provenance establish continuity; displayed positions never do.

const siteKey = (helixId, bp, direction) => `${helixId}:${bp}:${direction}`
const pairKey = (a, b) => `${a}|${b}`

export function ordinaryBackboneContinuations(design) {
  const pairs = new Set()
  const helices = new Map((design?.helices ?? []).map(h => [h.id, h]))
  const attachments = new Map()
  for (const op of (design?.deformations ?? [])) {
    if (op.type !== 'sweep' || op.params?.start_step !== 1) continue
    const direction = op.params.direction
    const bp = direction === 1 ? op.plane_a_bp : op.plane_b_bp
    const members = new Set(op.affected_helix_ids ?? [])
    for (const id of members) {
      const entries = attachments.get(id) ?? []
      entries.push({ bp, direction, members })
      attachments.set(id, entries)
    }
  }

  // Explicit junctions retain their arc presentation, even at an otherwise
  // ordinary attachment. Routing still respects their connected topology.
  const junctions = new Set()
  const addJunction = (a, b) => {
    junctions.add(pairKey(a, b))
    junctions.add(pairKey(b, a))
  }
  for (const fl of (design?.forced_ligations ?? [])) {
    addJunction(siteKey(fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction),
      siteKey(fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction))
  }
  for (const xo of (design?.crossovers ?? [])) {
    addJunction(siteKey(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand),
      siteKey(xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand))
  }

  const attaches = (helix, bp, otherHelix, otherBp) =>
    helix.lattice_frame_id != null && (attachments.get(helix.id) ?? []).some(a =>
      bp === a.bp && otherBp === a.bp - a.direction && !a.members.has(otherHelix.id))

  for (const strand of (design?.strands ?? [])) {
    if (strand.is_reference) continue
    const domains = strand.domains ?? []
    for (let i = 1; i < domains.length; i++) {
      const a = domains[i - 1], b = domains[i]
      if (a.overhang_id || a.binds_overhang_id || b.overhang_id || b.binds_overhang_id) continue
      const ha = helices.get(a.helix_id), hb = helices.get(b.helix_id)
      if (!ha || !hb || ha.id === hb.id || a.direction !== b.direction) continue
      if (ha.direction !== hb.direction || !ha.grid_pos || !hb.grid_pos) continue
      if (ha.grid_pos[0] !== hb.grid_pos[0] || ha.grid_pos[1] !== hb.grid_pos[1]) continue
      if ((ha.lattice_frame_id ?? null) === (hb.lattice_frame_id ?? null)) continue
      const step = a.direction === 'FORWARD' ? 1 : -1
      if (b.start_bp !== a.end_bp + step) continue
      const key = pairKey(siteKey(a.helix_id, a.end_bp, a.direction),
        siteKey(b.helix_id, b.start_bp, b.direction))
      if (junctions.has(key)) continue
      if (attaches(ha, a.end_bp, hb, b.start_bp) || attaches(hb, b.start_bp, ha, a.end_bp)) pairs.add(key)
    }
  }
  return pairs
}

export function isOrdinaryBackboneContinuation(pairs, from, to) {
  return pairs.has(pairKey(siteKey(from.helix_id, from.bp_index, from.direction),
    siteKey(to.helix_id, to.bp_index, to.direction)))
}
