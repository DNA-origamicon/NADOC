import * as THREE from 'three'
import { baseKey } from './base_ref.js'
import { buildNativeConnectionLines, writeNativeConnectionArc } from './native_connection_lines.js'
import { buildVolumeExtras, paintVolumeExtras } from './view_volume_extras.js'
import { buildStapleColorMap, orderStrandNucleotides } from './helix_renderer.js'
import { ordinaryBackboneContinuations, isOrdinaryBackboneContinuation } from './backbone_continuations.js'
import { computeAtomStrandColors } from './color_util.js'

/** Connections use both selected and neighboring endpoints, in the source's local frame. */
export function buildZoomConnections({ root, design, entries, selectedKeys, bounds, matrix, representation, state, coloring, selectionOnly = false }) {
  const visible = entries.filter(e => selectedKeys.has(baseKey(e.nuc, e.nuc.copy_k ?? 0)) || (!selectionOnly && bounds.containsPoint(e.pos.clone().applyMatrix4(matrix))))
  const geometry = visible.map(e => ({ ...e.nuc, backbone_position: e.pos.toArray() }))
  const sites = new Map(geometry.map(n => [`${n.helix_id}:${n.bp_index}:${n.direction}`, n]))
  const site = n => `${n.helix_id}:${n.bp_index}:${n.direction}`
  const pair = (a, b) => JSON.stringify([site(a), site(b)].sort())
  const byStrand = new Map(), continuations = ordinaryBackboneContinuations(design)
  for (const { nuc } of entries) {
    if (!nuc.strand_id || nuc.strand_id.startsWith('__lnk__') || nuc.is_flexible_segment) continue
    if (!byStrand.has(nuc.strand_id)) byStrand.set(nuc.strand_id, [])
    byStrand.get(nuc.strand_id).push(nuc)
  }
  const routedPairs = new Map()
  for (const nucs of byStrand.values()) {
    orderStrandNucleotides(nucs)
    for (let i = 1; i < nucs.length; i++) {
      const a = nucs[i - 1], b = nucs[i]
      if (site(a) !== site(b)) routedPairs.set(pair(a, b), [a, b])
    }
  }
  const visibleKeys = new Map(geometry.map(n => [baseKey(n, n.copy_k ?? 0), n]))
  const endpoints = record => {
    const halves = record.half_a ? [record.half_a, record.half_b] : [
      { helix_id: record.three_prime_helix_id, index: record.three_prime_bp, strand: record.three_prime_direction },
      { helix_id: record.five_prime_helix_id, index: record.five_prime_bp, strand: record.five_prime_direction },
    ]
    const addresses = halves.map(h => ({ helix_id: h.helix_id, bp_index: h.index, direction: h.strand }))
    const routed = routedPairs.get(pair(...addresses))
    // A loop has multiple beads at one site. Use the actual strand junction's
    // copies (not the last bead at each site), and never substitute an unselected copy.
    if (routed) return addresses.map(n => {
      const endpoint = routed.find(r => site(r) === site(n))
      return visibleKeys.get(baseKey(endpoint, endpoint.copy_k ?? 0))
    })
    return addresses.map(n => sites.get(site(n)))
  }
  const included = record => {
    const pair = endpoints(record)
    if (!pair.every(Boolean)) return false
    const belongsToSelection = pair.every(n => selectedKeys.has(baseKey(n, n.copy_k ?? 0)))
    return selectionOnly ? belongsToSelection : !belongsToSelection
  }
  const subset = { ...design, crossovers: (design.crossovers ?? []).filter(included), forced_ligations: (design.forced_ligations ?? []).filter(included) }
  const records = [...subset.crossovers, ...subset.forced_ligations]
  const group = new THREE.Group(); group.name = 'zoom-volume-connections'; root.add(group)
  const strands = computeAtomStrandColors({ ...state, currentDesign: design, coloringMode: coloring }, buildStapleColorMap(geometry, design))
  const arcs = records.filter(r => !r.extra_bases?.length).map(record => {
    const [a, b] = endpoints(record)
    return { crossover_id: record.id, from: new THREE.Vector3(...a.backbone_position), to: new THREE.Vector3(...b.backbone_position), color: strands.get(a.strand_id) ?? 0x0070bb }
  })
  // Native cross-helix cones have zero radius: their visible connection is an
  // arc, including imported routing with no explicit crossover record. Derive
  // adjacency BEFORE filtering the selection so omitted bases never get bridged.
  const authoredPairs = new Set(records.map(r => pair(...endpoints(r))))
  for (const nucs of byStrand.values()) {
    for (let i = 1; i < nucs.length; i++) {
      const a = nucs[i - 1], b = nucs[i]
      if (a.helix_id === b.helix_id || a.is_surface_capture || b.is_surface_capture ||
          a.helix_id.startsWith('__lnk__') || b.helix_id.startsWith('__lnk__') ||
          isOrdinaryBackboneContinuation(continuations, a, b) || authoredPairs.has(pair(a, b))) continue
      const ka = baseKey(a, a.copy_k ?? 0), kb = baseKey(b, b.copy_k ?? 0)
      const va = visibleKeys.get(ka), vb = visibleKeys.get(kb)
      if (!va || !vb || (selectedKeys.has(ka) && selectedKeys.has(kb)) !== selectionOnly) continue
      arcs.push({ from: new THREE.Vector3(...va.backbone_position), to: new THREE.Vector3(...vb.backbone_position),
        color: strands.get(a.strand_id) ?? 0x0070bb })
    }
  }
  const lines = buildNativeConnectionLines(arcs, selectionOnly ? 'zoom-selection' : 'zoom-context')
  if (lines) {
    for (const arc of arcs) writeNativeConnectionArc(lines.positions, arc.vertIdx, arc.from, arc.from.clone().add(arc.to).multiplyScalar(.5), arc.to)
    lines.geo.attributes.position.needsUpdate = true
    group.add(lines.line)
  }
  // Keep inserted residues and their native curved backbone, including saved poses.
  const extras = buildVolumeExtras(subset, [...geometry, ...records.flatMap(endpoints)], group, representation === 'full' ? 'full' : 'beads')
  paintVolumeExtras(extras, { columns: new Map(geometry.map(n => [`${n.helix_id}:${n.bp_index}`, 'full'])), design, mode: coloring, strands, nucAlphas: new Map() })
  return { group, count: arcs.length + records.filter(r => r.extra_bases?.length).length, dispose() {
    group.traverse(o => {
      if (o.geometry && !o.geometry.userData.shared) o.geometry.dispose()
      for (const m of Array.isArray(o.material) ? o.material : o.material ? [o.material] : []) m.dispose()
      if (o.isInstancedMesh) o.dispose()
    })
    group.removeFromParent()
  } }
}
