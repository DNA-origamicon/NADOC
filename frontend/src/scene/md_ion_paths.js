import * as THREE from 'three'
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import { initGrapheneRepresentation } from './graphene_representation.js'

export const ION_PATH_COLORS = { NA: 0xab5cf2, CL: 0x1ff01f, MG: 0xffdc32, K: 0x8f40d4, CA: 0x3dff00 }

// Stable pseudo-random order spreads a percentage across time and ion species.
// Prefixes remain nested: increasing the slider never removes an existing path.
function pathHash(path) {
  const key = `${path.ion_serial}:${path.crossing_frame}:${path.direction}:${path.species}`
  let hash = 2166136261
  for (let i = 0; i < key.length; i++) hash = Math.imul(hash ^ key.charCodeAt(i), 16777619)
  return hash >>> 0
}

/** Coalesce overlapping crossing windows, while retaining exact percentage prefixes.
 * Each segment is drawn once at the earliest selected crossing that includes it.
 */
export function ionPathBatches(data) {
  if (!data || !Array.isArray(data.paths) || !data.pore) throw new Error('Invalid ion-path data')
  const ordered = data.paths.map((path, index) => ({ path, index, hash: pathHash(path) }))
    .sort((a, b) => a.hash - b.hash || a.index - b.index)
  const groups = new Map(), species = new Map(), absent = 0xffffffff
  for (let rank = ordered.length - 1; rank >= 0; rank--) {
    const { path, index } = ordered[rank]
    const coords = data.tracks ? data.tracks[path.track] : path.positions
    const offset = path.offset || [0, 0, 0]
    const key = `${data.tracks ? path.track : index}:${offset.join(',')}:${path.species}`
    if (!groups.has(key)) groups.set(key, { coords, offset, species: path.species,
      priority: new Uint32Array(Math.max(0, coords.length / 3 - 1)).fill(absent) })
    const start = path.point_start || 0, count = path.point_count ?? coords.length / 3
    groups.get(key).priority.fill(rank, start, start + count - 1)
  }
  for (const group of groups.values()) {
    if (!species.has(group.species)) species.set(group.species, { counts: new Uint32Array(ordered.length) })
    const counts = species.get(group.species).counts
    for (const rank of group.priority) if (rank !== absent) counts[rank]++
  }
  for (const batch of species.values()) {
    let total = 0
    batch.ranks = []; batch.ends = []
    batch.cursors = new Uint32Array(ordered.length)
    for (let rank = 0; rank < ordered.length; rank++) {
      batch.cursors[rank] = total
      total += batch.counts[rank]
      if (batch.counts[rank]) { batch.ranks.push(rank); batch.ends.push(total) }
    }
    batch.positions = new Float32Array(total * 6)
  }
  for (const { coords, offset, priority, species: name } of groups.values()) {
    const batch = species.get(name)
    for (let segment = 0; segment < priority.length; segment++) {
      const rank = priority[segment]
      if (rank === absent) continue
      const dest = batch.cursors[rank]++ * 6
      for (let k = 0; k < 6; k++) batch.positions[dest + k] = coords[segment * 3 + k] + offset[k % 3]
    }
  }
  return species
}

/** Companions share the RMSF renderer’s coordinate frame and representation lifecycle. */
export function initMdIonPaths(scene, getCenter = () => new THREE.Vector3(), { onActiveChange = () => {} } = {}) {
  const group = new THREE.Group()
  group.name = 'mdIonPaths'
  scene.add(group)
  let active = false
  let width = 2, percentage = 100, totalPaths = 0, shownPaths = 0
  let graphene = null
  let grapheneDisplay = { visible: true, representation: 'plane' }
  const pathBatches = []
  function clearGeometry() {
    graphene?.dispose(); graphene = null
    pathBatches.length = 0
    totalPaths = shownPaths = 0
    for (const child of [...group.children]) {
      child.geometry.dispose()
      child.material.dispose()
      child.dispose?.()
      group.remove(child)
    }
  }
  function clear() {
    clearGeometry()
    const wasActive = active
    active = false
    // Let the preview owner restore its current representation/visibility, which
    // may have changed since the original scene snapshot was taken.
    if (wasActive) onActiveChange(false)
  }
  function setGrapheneDisplay(settings) {
    grapheneDisplay = { ...grapheneDisplay, ...settings }
    graphene?.setDisplay(grapheneDisplay)
    const rim = group.getObjectByName('nanoporeAperture')
    if (rim) rim.visible = grapheneDisplay.visible !== false
  }
  function setWidth(value) {
    width = Math.max(0.5, Math.min(12, Number(value) || 2))
    for (const { lines } of pathBatches) lines.material.linewidth = width
  }
  function setPercentage(value) {
    const number = Number(value)
    percentage = Number.isFinite(number) ? Math.max(0, Math.min(100, number)) : 100
    shownPaths = Math.round(totalPaths * percentage / 100)
    for (const { lines, ranks, ends } of pathBatches) {
      // All segments of a path appear together. Only change the GPU instance
      // count; the full geometry and the origami/pore remain untouched.
      let lo = 0, hi = ranks.length
      while (lo < hi) {
        const mid = (lo + hi) >>> 1
        if (ranks[mid] < shownPaths) lo = mid + 1
        else hi = mid
      }
      lines.geometry.instanceCount = lo ? ends[lo - 1] : 0
      lines.visible = lines.geometry.instanceCount > 0
    }
    return { shown: shownPaths, total: totalPaths, percentage }
  }
  return {
    clear, setWidth, setPercentage, setGrapheneDisplay,
    setData(data) {
      const species = ionPathBatches(data)
      clearGeometry()
      if (!active) { active = true; onActiveChange(true) }
      group.matrixAutoUpdate = false
      if (data.origami?.display_transform) group.matrix.fromArray(data.origami.display_transform)
      else group.matrix.identity()
      group.matrixWorldNeedsUpdate = true
      totalPaths = data.paths.length
      for (const [name, { positions, ranks, ends }] of species) {
        if (!positions.length) continue
        const geometry = new LineSegmentsGeometry()
        geometry.setPositions(positions)
        const material = new LineMaterial({ color: ION_PATH_COLORS[name] || 0xffffff, linewidth: width })
        const lines = new LineSegments2(geometry, material)
        lines.name = `ionPaths-${name}`
        group.add(lines)
        pathBatches.push({ lines, ranks, ends })
      }
      setPercentage(percentage)
      if (data.graphene?.length) {
        graphene = initGrapheneRepresentation(group)
        graphene.setDisplay(grapheneDisplay)
        graphene.setFrame(new Float32Array(data.graphene))
      }
      const radius = data.pore.radius_nm
      const rim = new THREE.Mesh(new THREE.RingGeometry(radius, radius + 0.15, 96),
        new THREE.MeshBasicMaterial({ color: 0xaaaaaa, side: THREE.DoubleSide }))
      rim.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...data.pore.normal).normalize())
      rim.name = 'nanoporeAperture'
      rim.visible = grapheneDisplay.visible !== false
      group.add(rim)
    },
    dispose() { clear(); scene.remove(group) },
  }
}
