/**
 * Overhang-resolver pipeline extracted from main.js. Pure builders over plain
 * design/geometry objects (no scene/store/DOM) — the orchestrator `_buildOvhgMaps`
 * stays in main.js because it reaches `designRenderer.getHelixCtrl()` and writes
 * the closure-level `_ovhg*` caches. Unit-tested in overhang_maps.test.js.
 *
 * Pipeline: spec → domain → junction → root, with two cross-validation maps
 * (geometry-based domain map, crossover-based junction map).
 */

// Map 1 — trivial; any missing entry here means design.overhangs is incomplete.
export function buildSpecMap(design) {
  return new Map((design?.overhangs ?? []).map(o => [o.id, o]))
}

// Map 2 (design path) — uses d.overhang_id === spec.id for exact match.
// NOTE: d.helix_id match was the original approach and is WRONG when a strand
// visits the same helix on two separate domains (findIndex returns first match).
export function buildDomainMapFromDesign(design, specMap) {
  const map = new Map()
  const strandById = new Map((design?.strands ?? []).map(strand => [strand.id, strand]))
  for (const spec of specMap.values()) {
    const strand = strandById.get(spec.strand_id)
    if (!strand) continue
    const domIdx = strand.domains.findIndex(d => d.overhang_id === spec.id)
    if (domIdx < 0) continue
    map.set(spec.id, { strand, domIdx, domain: strand.domains[domIdx] })
  }
  return map
}

// Map 2 (geometry path, cross-validation) — uses nuc.domain_index, which is the
// authoritative index emitted by the backend. Independent of d.overhang_id scan.
export function buildDomainMapFromGeom(design, backboneEntries) {
  const map = new Map()
  const strandById = new Map((design?.strands ?? []).map(strand => [strand.id, strand]))
  for (const entry of backboneEntries) {
    const id = entry.nuc.overhang_id
    if (!id || map.has(id)) continue
    const strand = strandById.get(entry.nuc.strand_id)
    if (!strand) continue
    const domIdx = entry.nuc.domain_index
    const domain = strand.domains[domIdx]
    if (domain) map.set(id, { strand, domIdx, domain })
  }
  return map
}

// Map 3 (crossover path) — reads design.crossovers for the exact (bp_index, direction)
// of the junction bead. design.crossovers contains all inter-helix strand transitions
// including those for inline overhangs created before overhang detection ran.
export function buildJunctionMapFromXovers(design, specMap, domainMap) {
  const map = new Map()
  const pairKey = (a, b) => a < b ? `${a}\0${b}` : `${b}\0${a}`
  const firstXoverByHelixPair = new Map()
  for (const xover of design?.crossovers ?? []) {
    const a = xover.half_a?.helix_id
    const b = xover.half_b?.helix_id
    if (a == null || b == null) continue
    const key = pairKey(a, b)
    if (!firstXoverByHelixPair.has(key)) firstXoverByHelixPair.set(key, xover)
  }
  for (const [id, spec] of specMap) {
    const domEntry = domainMap.get(id)
    if (!domEntry) continue
    const { strand, domIdx } = domEntry
    const parentDomIdx = domIdx === 0 ? 1 : domIdx - 1
    if (parentDomIdx < 0 || parentDomIdx >= strand.domains.length) continue
    const parentDom = strand.domains[parentDomIdx]
    const xover = firstXoverByHelixPair.get(pairKey(spec.helix_id, parentDom.helix_id))
    if (!xover) continue
    const side = xover.half_a?.helix_id === spec.helix_id ? xover.half_a : xover.half_b
    map.set(id, { junctionBp: side.index, junctionDir: side.strand })
  }
  return map
}

// Map 3 (domain-endpoint path, PRIMARY) — derives junction bp from domain start_bp/end_bp.
// In NADOC start_bp is ALWAYS the 5′ end regardless of direction, so the junction is:
//   overhang at 3' end of strand (domIdx > 0) → junction = 5' end of domain = start_bp
//   overhang at 5' end of strand (domIdx = 0) → junction = 3' end of domain = end_bp
// No direction check needed — the start_bp/end_bp convention handles it for HC and SQ.
export function buildJunctionMapFromDomains(domainMap) {
  const map = new Map()
  for (const [id, { domIdx, domain }] of domainMap) {
    const isFirst = domIdx === 0
    const junctionBp = isFirst ? domain.end_bp : domain.start_bp
    map.set(id, { junctionBp, junctionDir: domain.direction })
  }
  return map
}

// Map 4 — uses helixCtrl.lookupEntry for O(1) lookup. The key format matches
// the one used internally by helix_renderer: "helix_id:bp_index:direction".
export function buildRootMap(specMap, junctionMap, helixCtrl) {
  const map = new Map()
  for (const [id, { junctionBp, junctionDir }] of junctionMap) {
    const spec = specMap.get(id)
    if (!spec) continue
    const entry = helixCtrl?.lookupEntry(`${spec.helix_id}:${junctionBp}:${junctionDir}`)
    if (entry) map.set(id, { entry, pos: entry.pos })
  }
  return map
}
