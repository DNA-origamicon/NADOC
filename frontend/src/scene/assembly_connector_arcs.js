// Where to draw connector arcs along cross-part linker strands (assembly view).
//
// A linker strand's backbone "jumps" whenever two consecutive domains sit on
// DIFFERENT helices; that jump is rendered as a tube arc. This covers:
//   - ds linkers (`__a` / `__b`): the complement↔bridge junction.
//   - length>0 ss linkers (`__s`): both complement↔bridge junctions.
//   - length-0 indirect ss linkers (`__s`, domains [comp_a, comp_b], no
//     bridge): the single direct complement↔complement jump.
//
// Pure data only — no THREE, no meshes — so it unit-tests without a GL context.
// Mirrors the backend `_connector_arc_endpoints` in
// backend/core/assembly_linker_relax.py (same "exactly one bridge / different
// helix" junction rule), kept in sync.

const _LNK_STRAND_RE = /^(__lnk__.+)__(a|b|s)$/

/**
 * @param {Array<{id?:string, color?:string, domains?:Array}>} linkerStrands
 *        assembly.assembly_strands (only `__lnk__…__(a|b|s)` ids are considered).
 * @param {Array<{strand_id?:string, helix_id?:string, bp_index?:number,
 *        backbone_position?:number[], base_position?:number[]}>} nucs
 *        world-space beads from GET /assembly/linker-geometry.
 * @returns {Array<{connId:string, colorCss:(string|undefined),
 *        a:number[], b:number[]}>} one entry per arc, in strand-traversal order.
 */
export function assemblyConnectorArcEndpoints(linkerStrands, nucs) {
  const posByKey = new Map()
  for (const n of nucs ?? []) {
    if (!n.strand_id) continue
    const p = n.backbone_position ?? n.base_position
    if (p) posByKey.set(`${n.strand_id}|${n.helix_id}|${n.bp_index}`, p)
  }
  const out = []
  for (const strand of linkerStrands ?? []) {
    const m = _LNK_STRAND_RE.exec(strand.id ?? '')
    if (!m) continue
    const connId = m[1].replace(/^__lnk__/, '')
    const domains = strand.domains ?? []
    for (let i = 0; i + 1 < domains.length; i++) {
      const d0 = domains[i], d1 = domains[i + 1]
      // Arc only at a real backbone jump (different helices). A same-helix
      // continuation would be a degenerate zero-length arc.
      if (d0.helix_id === d1.helix_id) continue
      const a = posByKey.get(`${strand.id}|${d0.helix_id}|${d0.end_bp}`)
      const b = posByKey.get(`${strand.id}|${d1.helix_id}|${d1.start_bp}`)
      if (!a || !b) continue
      // Drop degenerate (coincident) jumps — 1e-3 nm, squared.
      const dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2]
      if (dx * dx + dy * dy + dz * dz <= 1e-6) continue
      out.push({ connId, colorCss: strand.color, a, b })
    }
  }
  return out
}
