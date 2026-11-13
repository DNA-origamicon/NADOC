import * as THREE from 'three'
import { canonicalSelection } from './selection_model.js'
import { matchTargetEntries, unresolvedBaseKeys } from './annotation_targets.js'
import { baseKey, xbKey } from './base_ref.js'
import { volumeBackboneEntries } from './view_volumes.js'
import { simBeadIndex } from './crossover_connections.js'

/** A finite core volume even for one base. Padding is independent of the shell. */
export function submodelBounds(points, paddingNm = 1) {
  if (!points.length || !Number.isFinite(paddingNm) || paddingNm <= 0) return null
  const bounds = new THREE.Box3()
  for (const point of points) {
    if (!point || ![point.x, point.y, point.z].every(Number.isFinite)) return null
    bounds.expandByPoint(point)
  }
  bounds.expandByScalar(paddingNm)
  return { shape: 'box', min_corner: bounds.min.toArray(), max_corner: bounds.max.toArray(), rotation: [0, 0, 0, 1] }
}

export function hasSubmodelSelection(state) {
  return state.assemblyActive
    ? !!(state.activeInstanceId || state.activeGroupId || state.multiSelectedInstanceIds?.size || state.multiSelectedInstanceIds?.length || state.assemblyOverhangSelection?.length)
    : canonicalSelection(state).items.length > 0
}

function selectedPoints(refs, design, entries, resolveBasePosition) {
  const supported = new Set(['base', 'end', 'bond', 'domain', 'strand', 'cluster', 'part_group', 'overhang', 'extension', 'crossover'])
  if (refs.some(ref => !supported.has(ref.kind))) throw new Error('Submodel selection must contain DNA elements only.')
  const matched = matchTargetEntries(refs, design, entries)
  const points = matched.map(entry => entry.pos)
  const keys = new Set(matched.map(entry => baseKey(entry.nuc, entry.nuc.copy_k ?? 0)))
  const missing = new Set(unresolvedBaseKeys(refs, matched))
  // Crossover inserts live outside ordinary backbone entries. Include them when
  // the crossover itself or both of its endpoints belong to the selection.
  const junctions = [...(design?.crossovers ?? []), ...(design?.forced_ligations ?? []).map(fl => ({
    id: fl.id, extra_bases: fl.extra_bases,
    half_a: { helix_id: fl.three_prime_helix_id, index: fl.three_prime_bp, strand: fl.three_prime_direction },
    half_b: { helix_id: fl.five_prime_helix_id, index: fl.five_prime_bp, strand: fl.five_prime_direction },
  }))]
  for (const xo of junctions) {
    const halves = [xo.half_a, xo.half_b].map(h => `${h.helix_id}:${h.index}:${h.strand}`)
    if (refs.some(ref => ref.kind === 'crossover' && ref.id === xo.id) || halves.every(key => keys.has(key))) {
      for (let k = 0; k < (xo.extra_bases?.length ?? 0); k++) missing.add(xbKey(xo.id, k))
    }
  }
  for (const key of missing) {
    const position = resolveBasePosition?.(key)
    if (!position) throw new Error('Selected base positions are not available. Show the selected DNA in Full representation and try again.')
    points.push(position)
  }
  if (!points.length) throw new Error('Select DNA bases, domains, strands, crossovers, or clusters with available geometry.')
  return points
}

/** Extra-base bead positions in the same local frame as assembly nucleotides. */
export function assemblyInsertPositions(data) {
  const result = new Map(), geometry = data.extraBaseGeometry
  if (!geometry?.beadsMesh) return result
  geometry.beadsMesh.updateWorldMatrix(true, false)
  const toLocal = data.matrixWorld.clone().invert().multiply(geometry.beadsMesh.matrixWorld)
  const matrix = new THREE.Matrix4()
  for (const arc of geometry.arcData ?? []) for (let i = 0; i < arc.beadCount; i++) {
    geometry.beadsMesh.getMatrixAt(arc.beadStartIdx + i, matrix)
    result.set(xbKey(arc.xoId, simBeadIndex(i, arc.beadCount, arc.simReversed)), new THREE.Vector3().setFromMatrixPosition(matrix).applyMatrix4(toLocal))
  }
  return result
}

/** Resolve a snapshot on click; never change selection, topology, or live vectors. */
export function submodelFromSelection(state, { designRenderer, assemblyRenderer, resolveBasePosition, getAssemblyCluster = () => null } = {}) {
  const points = []
  if (!state.assemblyActive) {
    const refs = canonicalSelection(state).items
    const entries = volumeBackboneEntries(designRenderer?.getBackboneEntries?.() ?? [], state.currentGeometry ?? [])
    points.push(...selectedPoints(refs, state.currentDesign, entries, resolveBasePosition))
  } else {
    const ids = new Set(state.multiSelectedInstanceIds ?? [])
    if (state.activeInstanceId) ids.add(state.activeInstanceId)
    const visited = new Set()
    const visit = id => {
      if (visited.has(id)) return
      visited.add(id)
      const group = state.currentAssembly?.groups?.find(g => g.id === id)
      group?.instance_ids?.forEach(id => ids.add(id))
      group?.subgroup_ids?.forEach(visit)
    }
    if (state.activeGroupId) visit(state.activeGroupId)
    const cluster = getAssemblyCluster()
    const targets = state.assemblyOverhangSelection?.length
      ? state.assemblyOverhangSelection.map(o => ({ id: o.instanceId, refs: [{ kind: 'overhang', id: o.overhangId }] }))
      : cluster && ids.has(cluster.instanceId)
        ? [{ id: cluster.instanceId, refs: [{ kind: 'cluster', id: cluster.clusterId }] }]
        : [...ids].map(id => ({ id, refs: null }))
    for (const target of targets) {
      const data = assemblyRenderer?.getInstanceBackboneEntries?.(target.id)
      const design = assemblyRenderer?.getInstanceDesign?.(target.id)
      if (!data?.matrixWorld) throw new Error('Selected assembly geometry is still loading.')
      const entries = volumeBackboneEntries(data.entries ?? [], data.nucleotides ?? [])
      const inserts = assemblyInsertPositions(data)
      // Instance entries are local; apply the live instance/group transform once.
      const local = target.refs ? selectedPoints(target.refs, design, entries, key => inserts.get(key)) : [...entries.map(e => e.pos), ...inserts.values()]
      if (!local.length) throw new Error('Selected assembly geometry is still loading.')
      points.push(...local.map(point => point.clone().applyMatrix4(data.matrixWorld)))
    }
  }
  const box = submodelBounds(points)
  if (!box) throw new Error('Select DNA with finite positions before defining a submodel.')
  return box
}
