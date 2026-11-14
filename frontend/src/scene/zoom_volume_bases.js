import * as THREE from 'three'
import { baseKey, xbKey } from './base_ref.js'
import { buildCrossoverConnections, simBeadIndex, setExtraBaseConnectors } from './crossover_connections.js'
import { computeAtomStrandColors } from './color_util.js'
import { buildStapleColorMap, orderStrandNucleotides } from './helix_renderer.js'
import { BASE_COLORS } from './helix_renderer/palette.js'

/** Complete a selected insert junction's attachment residues for display only.
 * Require the whole insert and at least one selected endpoint. An isolated base
 * selection or a partial insert remains exact; never infer a new covalent edge.
 */
export function completeZoomJunctions(selected, entries) {
  const key = e => baseKey(e.nuc, e.nuc.copy_k ?? 0)
  const wanted = new Set(selected.map(key)), added = new Set(), inserts = new Map()
  for (const entry of entries) {
    if (!entry.zoomExtra?.endpointKeys) continue
    const id = entry.nuc.crossover_id
    if (!inserts.has(id)) inserts.set(id, [])
    inserts.get(id).push(entry)
  }
  for (const group of inserts.values()) {
    const endpoints = group[0].zoomExtra.endpointKeys
    if (group.every(e => wanted.has(key(e))) && endpoints.some(k => wanted.has(k))) {
      for (const k of endpoints) if (!wanted.has(k)) added.add(k)
    }
  }
  return [...selected, ...entries.filter(e => added.has(key(e)))]
}

/** Complete display membership, including residues owned by the crossover renderer.
 * These are transient render records, never authored nucleotides or topology.
 */
export function zoomBaseEntries(design, live = [], geometry = [], renderer = null, resolveBasePosition = () => null) {
  const entries = live.filter(e => e?.nuc && e?.pos)
  const found = new Set(entries.map(e => baseKey(e.nuc, e.nuc.copy_k ?? 0)))
  for (const nuc of geometry) {
    const key = baseKey(nuc, nuc.copy_k ?? 0)
    if (found.has(key) || nuc.backbone_position?.length !== 3 || !nuc.backbone_position.every(Number.isFinite)) continue
    const pos = (nuc.is_flexible_segment || nuc.helix_id?.startsWith('__lnk__')) ? resolveBasePosition(key) : null
    const displayed = pos ? { ...nuc, backbone_position: pos.toArray(),
      base_position: nuc.base_position?.map((v, i) => v + pos.getComponent(i) - nuc.backbone_position[i]),
      slab_position: nuc.slab_position?.map((v, i) => v + pos.getComponent(i) - nuc.backbone_position[i]) ?? nuc.slab_position } : nuc
    entries.push({ nuc: displayed, pos: pos ?? new THREE.Vector3(...nuc.backbone_position) }); found.add(key)
  }
  const extras = buildCrossoverConnections(design, entries.map(e => renderer ? e.nuc : { ...e.nuc, backbone_position: e.pos.toArray() }), buildStapleColorMap(geometry, design), {})
  for (const arc of extras?.arcData ?? []) for (let i = 0; i < arc.beadCount; i++) {
    const k = simBeadIndex(i, arc.beadCount, arc.simReversed)
    if (found.has(xbKey(arc.xoId, k))) continue
    const index = arc.beadStartIdx + i
    const target = { helix_id: '__xb__', crossover_id: arc.xoId, k }
    const livePose = renderer?.xoverResidueInfo?.(target)
    const parts = [extras.beadsMesh, extras.slabsMesh, extras.slabConnMesh].map((mesh, j) => {
      const matrix = new THREE.Matrix4(); mesh.getMatrixAt(index, matrix)
      const pose = livePose?.[['beadMatrix', 'slabMatrix', 'slabConnectorMatrix'][j]]
      return { geometry: mesh.geometry, matrix: pose ?? matrix, color: j ? arc.slabBaseColor : arc.beadBaseColor }
    })
    const referenceMatrix = new THREE.Matrix4(); extras.beadsMesh.getMatrixAt(index, referenceMatrix)
    const referencePosition = new THREE.Vector3().setFromMatrixPosition(referenceMatrix)
    const pos = new THREE.Vector3().setFromMatrixPosition(parts[0].matrix)
    const nuc = { helix_id: `__xb__:${arc.xoId}`, bp_index: k, direction: arc.nucA.direction,
      crossover_id: arc.xoId, extra_base_k: k, strand_id: arc.nucA.strand_id,
      domain_index: arc.nucA.domain_index, strand_type: arc.nucA.strand_type, base: arc.sequence[k], backbone_position: referencePosition.toArray() }
    const connections = []
    const keys = [baseKey(arc.nucA, arc.nucA.copy_k ?? 0), ...Array.from({ length: arc.beadCount }, (_, slot) => xbKey(arc.xoId, simBeadIndex(slot, arc.beadCount, arc.simReversed))), baseKey(arc.nucB, arc.nucB.copy_k ?? 0)]
    for (const slot of i === 0 ? [0, 1] : [i + 1]) {
      const matrix = new THREE.Matrix4(); extras.connMesh.getMatrixAt(arc.connStartIdx + slot, matrix)
      connections.push({ from: keys[slot], to: keys[slot + 1], geometry: extras.connMesh.geometry, matrix, color: arc.beadBaseColor })
    }
    entries.push({ nuc, pos, zoomExtra: { parts, target, connections, endpointKeys: [keys[0], keys.at(-1)] } })
  }
  // Only shared geometry templates and value matrices escape this temporary builder.
  extras?.group.traverse(o => { o.material?.dispose(); if (o.isInstancedMesh) o.dispose() })
  return entries
}

/** Copy the native bead/slab matrices; never substitute new molecular placements. */
export function buildZoomBaseExtras(root, entries, representation, coloring, opacity, renderer = null, state = {}, neighbors = []) {
  if (!['full', 'beads', 'cylinders'].includes(representation)) return null
  const group = new THREE.Group(); root.add(group)
  const strands = computeAtomStrandColors({ ...state, currentDesign: state.currentDesign ?? {}, coloringMode: coloring }, buildStapleColorMap(entries.map(e => e.nuc), state.currentDesign ?? {}))
  const copies = [], owned = new Set(entries.map(e => baseKey(e.nuc, e.nuc.copy_k ?? 0)))
  const allEntries = [...entries, ...neighbors]
  const keys = new Set(allEntries.map(e => baseKey(e.nuc, e.nuc.copy_k ?? 0)))
  for (const entry of entries.filter(e => e.zoomExtra)) {
    const parts = representation === 'full' ? entry.zoomExtra.parts : entry.zoomExtra.parts.slice(0, 1)
    parts.forEach((part, index) => {
      const strandColor = strands.get(entry.nuc.strand_id) ?? part.color
      const color = coloring === 'base' ? BASE_COLORS[entry.nuc.base?.toUpperCase()] ?? strandColor : strandColor
      const mesh = new THREE.Mesh(part.geometry, new THREE.MeshPhongMaterial({ color, opacity, transparent: true }))
      mesh.matrixAutoUpdate = false; mesh.matrix.copy(part.matrix); group.add(mesh)
      copies.push({ mesh, index, entry })
    })
  }
  for (const entry of allEntries.filter(e => e.zoomExtra)) {
    for (const connection of entry.zoomExtra.connections ?? []) {
      if (!keys.has(connection.from) || !keys.has(connection.to)
        || (!owned.has(connection.from) && !owned.has(connection.to))) continue
      const mesh = new THREE.Mesh(connection.geometry, new THREE.MeshPhongMaterial({ color: strands.get(entry.nuc.strand_id) ?? connection.color, opacity, transparent: true }))
      mesh.matrixAutoUpdate = false; mesh.matrix.copy(connection.matrix); group.add(mesh)
      copies.push({ mesh, entry, index: -1, connection })
    }
  }
  return { update(live = []) {
    const poses = new Map(), positions = new Map(live.map(e => [baseKey(e.nuc, e.nuc.copy_k ?? 0), e.pos]))
    for (const { mesh, index, entry, connection } of copies) {
      if (connection) {
        const a = positions.get(connection.from), b = positions.get(connection.to)
        if (a && b) {
          setExtraBaseConnectors({ setMatrixAt: (_, matrix) => mesh.matrix.copy(matrix) }, 0, [a, b], 1, null)
        }
        continue
      }
      if (!poses.has(entry)) poses.set(entry, renderer?.xoverResidueInfo?.(entry.zoomExtra.target))
      const pose = poses.get(entry)
      const matrix = pose?.[['beadMatrix', 'slabMatrix', 'slabConnectorMatrix'][index]]
      if (matrix) mesh.matrix.copy(matrix)
    }
  }, dispose() { group.removeFromParent(); for (const { mesh } of copies) mesh.material.dispose() } }
}

/** Preserve full-source adjacency before trimming to an arbitrary subset. */
export function zoomBackbonePairs(entries) {
  const strands = new Map(), pairs = new Set()
  const inserted = new Set(entries.filter(e => e.zoomExtra?.endpointKeys).map(e => JSON.stringify([...e.zoomExtra.endpointKeys].sort())))
  for (const entry of entries) {
    const n = entry.nuc
    if (entry.zoomExtra || !n?.strand_id) continue
    if (!strands.has(n.strand_id)) strands.set(n.strand_id, [])
    strands.get(n.strand_id).push(n)
  }
  for (const nucs of strands.values()) {
    orderStrandNucleotides(nucs)
    for (let i = 1; i < nucs.length; i++) {
      const pair = JSON.stringify([baseKey(nucs[i - 1], nucs[i - 1].copy_k ?? 0), baseKey(nucs[i], nucs[i].copy_k ?? 0)].sort())
      if (!inserted.has(pair)) pairs.add(pair)
    }
  }
  return pairs
}
