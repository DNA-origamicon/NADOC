import * as THREE from 'three'
import { computeGroupHiddenInstanceIds } from './assembly_groups_util.js'
import { withSkippedColumnPoints } from './view_volume_points.js'

function recordsFor(assembly, renderer) {
  const hidden = computeGroupHiddenInstanceIds(assembly), records = []
  for (const instance of assembly?.instances ?? []) {
    if (instance.visible === false || hidden.has(instance.id)) continue
    const data = renderer.getInstanceRenderData(instance.id)
    const matrix = renderer.getLiveTransform(instance.id)
    if (data && matrix) records.push({ id: instance.id, nucleotides: data.nucleotides,
      helices: data.design?.helices, matrix })
  }
  return records
}

function localPoints(nucleotides, helices, cache) {
  let local = cache.get(nucleotides)
  const skips = JSON.stringify((helices ?? []).map(helix => [helix.id, helix.loop_skips]))
  let unchanged = local?.base.length === nucleotides.length && local.skips === skips
  for (let i = 0; unchanged && i < nucleotides.length; i++) {
    const nucleotide = nucleotides[i], position = nucleotide.backbone_position
    unchanged = local.base[i].key === `${nucleotide.helix_id}:${nucleotide.bp_index}`
      && position?.length === local.positions[i]?.length
      && (!position || position.every((value, axis) => value === local.positions[i][axis]))
  }
  if (unchanged) return local
  const base = nucleotides.map(n => ({ key: `${n.helix_id}:${n.bp_index}`, position: n.backbone_position }))
  local = { base, skips, positions: base.map(point => point.position?.slice()),
    points: withSkippedColumnPoints(base, helices) }
  cache.set(nucleotides, local)
  return local
}

function prepareLocalPoints(records, localCache) {
  const sources = new Map()
  for (const record of records) {
    if (!record.nucleotides) continue
    const byHelices = sources.get(record.nucleotides) ?? new Map()
    if (!byHelices.has(record.helices)) byHelices.set(record.helices,
      localPoints(record.nucleotides, record.helices, localCache))
    sources.set(record.nucleotides, byHelices)
    record.local = byHelices.get(record.helices)
  }
}

function materializePoints(records) {
  const points = [], position = new THREE.Vector3()
  for (const record of records) {
    const { local, matrix } = record
    if (!local) continue
    const prefix = `${encodeURIComponent(record.id)}|`
    for (const point of local.points) if (point.position) points.push({
      key: prefix + point.key, position: position.fromArray(point.position).applyMatrix4(matrix).toArray(),
    })
  }
  return points
}

/** Preserve native world positions and source-local skipped-column samples. */
export function assemblyVolumePoints(assembly, renderer) {
  const records = recordsFor(assembly, renderer)
  prepareLocalPoints(records, new WeakMap())
  return materializePoints(records)
}

/** Active volume gestures reuse membership inputs until visible membership,
 * source geometry/helix metadata, or an actual live transform changes. Clear
 * when volumes are disabled so large world-point arrays are not retained idle. */
export function createAssemblyVolumePointCache(renderer) {
  let records = null, points = null, localCache = new WeakMap()
  function clear() { records = null; points = null; localCache = new WeakMap() }
  return {
    clear,
    get(assembly) {
      const next = recordsFor(assembly, renderer)
      prepareLocalPoints(next, localCache)
      const unchanged = records?.length === next.length && next.every((record, index) => {
        const old = records[index]
        return record.id === old.id && record.local === old.local
          && record.matrix.elements.every((value, element) => value === old.matrix.elements[element])
      })
      if (unchanged) return points
      points = materializePoints(next)
      // A renderer may return a mutable live Matrix4 rather than a fresh copy.
      records = next.map(record => ({ ...record, matrix: record.matrix.clone() }))
      return points
    },
  }
}
