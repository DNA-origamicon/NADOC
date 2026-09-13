import * as THREE from 'three'
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import { initGrapheneRepresentation } from './graphene_representation.js'
import { colormapHex } from '../ui/colormaps.js'

export const ION_PATH_COLORS = { NA: 0xab5cf2, CL: 0x1ff01f, MG: 0xffdc32, K: 0x8f40d4, CA: 0x3dff00 }

function pathHash(path) {
  const key = `${path.ion_serial}:${path.crossing_frame}:${path.direction}:${path.species}`
  let hash = 2166136261
  for (let i = 0; i < key.length; i++) hash = Math.imul(hash ^ key.charCodeAt(i), 16777619)
  return hash >>> 0
}

/** Coalesce overlapping crossing windows, while retaining exact percentage prefixes. */
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
      priority: new Uint32Array(Math.max(0, coords.length / 3 - 1)).fill(absent),
      frames: new Uint32Array(Math.max(0, coords.length / 3 - 1)) })
    const start = path.point_start || 0, count = path.point_count ?? coords.length / 3
    const group = groups.get(key)
    group.priority.fill(rank, start, start + count - 1)
    for (let segment = start; segment < start + count - 1; segment++) {
      group.frames[segment] = (path.start_frame || 0) + segment - start
    }
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
    batch.frames = new Uint32Array(total)
  }
  for (const { coords, offset, priority, frames, species: name } of groups.values()) {
    const batch = species.get(name)
    for (let segment = 0; segment < priority.length; segment++) {
      const rank = priority[segment]
      if (rank === absent) continue
      const dest = batch.cursors[rank]++ * 6
      for (let k = 0; k < 6; k++) batch.positions[dest + k] = coords[segment * 3 + k] + offset[k % 3]
      batch.frames[dest / 6] = frames[segment]
    }
  }
  return species
}

/** Average directed, saved-frame displacements in occupied cubic spatial bins. */
export function ionVectorField(data, selectedSpecies = 'NA', density = 14) {
  const segments = ionPathBatches(data).get(selectedSpecies)?.positions || new Float32Array()
  density = Math.max(4, Math.min(1000000, Math.trunc(Number(density) || 14)))
  if (!segments.length) return { positions: new Float32Array(), vectors: new Float32Array(),
    magnitudes: new Float32Array(), cellSize: 1, maxMagnitude: 0, species: selectedSpecies }
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < segments.length; i += 6) for (let axis = 0; axis < 3; axis++) {
    const midpoint = (segments[i + axis] + segments[i + 3 + axis]) / 2
    min[axis] = Math.min(min[axis], midpoint); max[axis] = Math.max(max[axis], midpoint)
  }
  const span = Math.max(...max.map((value, axis) => value - min[axis]))
  const cellSize = Math.max(span / density, 1e-4)
  const bins = new Map()
  for (let i = 0; i < segments.length; i += 6) {
    const midpoint = [0, 1, 2].map(axis => (segments[i + axis] + segments[i + 3 + axis]) / 2)
    const key = midpoint.map((value, axis) => Math.floor((value - min[axis]) / cellSize)).join(',')
    if (!bins.has(key)) bins.set(key, { p: [0, 0, 0], v: [0, 0, 0], count: 0 })
    const bin = bins.get(key); bin.count++
    for (let axis = 0; axis < 3; axis++) {
      bin.p[axis] += midpoint[axis]
      bin.v[axis] += segments[i + 3 + axis] - segments[i + axis]
    }
  }
  const positions = [], vectors = [], magnitudes = []
  for (const bin of bins.values()) {
    const vector = bin.v.map(value => value / bin.count)
    const magnitude = Math.hypot(...vector)
    if (magnitude <= 1e-8) continue
    positions.push(...bin.p.map(value => value / bin.count))
    vectors.push(...vector); magnitudes.push(magnitude)
  }
  return { positions: new Float32Array(positions), vectors: new Float32Array(vectors),
    magnitudes: new Float32Array(magnitudes), cellSize,
    maxMagnitude: magnitudes.length ? Math.max(...magnitudes) : 0, species: selectedSpecies }
}

function disposeObject(object) {
  object.geometry?.dispose()
  object.material?.dispose()
  object.dispose?.()
  object.removeFromParent()
}

function createVectorArrows(field, species, magnitudeMode, arrowScale) {
  const arrows = new THREE.Group()
  arrows.name = `ionVectorField-${species}`
  const count = field.magnitudes.length
  if (!count) return arrows
  // InstancedMesh consumes instanceColor independently. Enabling vertexColors
  // without a geometry color attribute multiplies the instance color by black.
  const materialOptions = { color: 0xffffff }
  const shafts = new THREE.InstancedMesh(new THREE.CylinderGeometry(1, 1, 1, 8),
    new THREE.MeshBasicMaterial(materialOptions), count)
  shafts.name = `ionVectorShafts-${species}`
  const cones = new THREE.InstancedMesh(new THREE.ConeGeometry(1, 1, 8),
    new THREE.MeshBasicMaterial(materialOptions), count)
  cones.name = `ionVectorHeads-${species}`
  const start = new THREE.Vector3(), direction = new THREE.Vector3(), center = new THREE.Vector3()
  const quaternion = new THREE.Quaternion(), scale = new THREE.Vector3(), matrix = new THREE.Matrix4()
  const up = new THREE.Vector3(0, 1, 0), color = new THREE.Color()
  const baseColor = new THREE.Color(ION_PATH_COLORS[species] || 0xffffff)
  for (let i = 0; i < count; i++) {
    start.fromArray(field.positions, i * 3)
    direction.fromArray(field.vectors, i * 3).normalize()
    const relative = field.maxMagnitude ? field.magnitudes[i] / field.maxMagnitude : 0
    const baseLength = field.cellSize * (magnitudeMode === 'size' ? 0.25 + 0.75 * relative : 0.82)
    const length = arrowScale * baseLength
    const thickness = arrowScale * field.cellSize * (magnitudeMode === 'size' ? 0.025 + 0.055 * relative : 0.06)
    const headLength = arrowScale * Math.min(baseLength * 0.34, field.cellSize * 0.28)
    const shaftLength = Math.max(length - headLength, length * 0.5)
    color.copy(magnitudeMode === 'color'
      ? new THREE.Color().setHSL(0.66 * (1 - relative), 1, 0.5)
      : baseColor)
    quaternion.setFromUnitVectors(up, direction)
    center.copy(start).addScaledVector(direction, shaftLength / 2)
    scale.set(thickness, shaftLength, thickness)
    matrix.compose(center, quaternion, scale)
    shafts.setMatrixAt(i, matrix); shafts.setColorAt(i, color)
    center.copy(start).addScaledVector(direction, shaftLength + headLength / 2)
    scale.set(thickness * 2.25, headLength, thickness * 2.25)
    matrix.compose(center, quaternion, scale)
    cones.setMatrixAt(i, matrix); cones.setColorAt(i, color)
  }
  shafts.instanceMatrix.needsUpdate = true
  cones.instanceMatrix.needsUpdate = true
  if (shafts.instanceColor) shafts.instanceColor.needsUpdate = true
  if (cones.instanceColor) cones.instanceColor.needsUpdate = true
  arrows.add(shafts, cones)
  return arrows
}

/** Companions share the RMSF renderer’s coordinate frame and representation lifecycle. */
export function initMdIonPaths(scene, _getCenter = () => new THREE.Vector3(), { onActiveChange = () => {} } = {}) {
  const group = new THREE.Group()
  group.name = 'mdIonPaths'
  scene.add(group)
  let active = false, data = null, batches = null, mode = 'paths'
  let pathColor = { mode: 'species', lo: 0, hi: 1, colormap: 'turbo' }
  let width = 2, percentage = 100, totalPaths = 0, shownPaths = 0
  let graphene = null, vectorObject = null, vectorKey = null
  let vectorSettings = { species: 'NA', density: 14, magnitude: 'size', arrowScale: 1 }
  let grapheneDisplay = { visible: true, representation: 'plane' }
  const pathBatches = []
  function clearGeometry() {
    graphene?.dispose(); graphene = null
    for (const { lines } of pathBatches) disposeObject(lines)
    pathBatches.length = 0
    if (vectorObject) {
      for (const child of [...vectorObject.children]) disposeObject(child)
      vectorObject.removeFromParent(); vectorObject = null
    }
    vectorKey = null; data = null; batches = null
    totalPaths = shownPaths = 0
    for (const child of [...group.children]) disposeObject(child)
  }
  function clear() {
    clearGeometry()
    const wasActive = active
    active = false
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
      let lo = 0, hi = ranks.length
      while (lo < hi) {
        const mid = (lo + hi) >>> 1
        if (ranks[mid] < shownPaths) lo = mid + 1
        else hi = mid
      }
      lines.geometry.instanceCount = lo ? ends[lo - 1] : 0
      lines.visible = mode === 'paths' && lines.geometry.instanceCount > 0
    }
    return { shown: shownPaths, total: totalPaths, percentage }
  }
  function pathFrameRange() {
    if (!batches) return null
    let min = Infinity, max = -Infinity
    for (const { frames } of batches.values()) for (const frame of frames) {
      min = Math.min(min, frame); max = Math.max(max, frame)
    }
    return Number.isFinite(min) ? { min, max } : null
  }
  function recolorPaths() {
    for (const { lines, frames, name } of pathBatches) {
      const colors = new Float32Array(frames.length * 6)
      for (let i = 0; i < frames.length; i++) {
        const t = pathColor.mode === 'time'
          ? (frames[i] - pathColor.lo) / Math.max(1e-9, pathColor.hi - pathColor.lo)
          : 0
        const hex = pathColor.mode === 'time' ? colormapHex(pathColor.colormap, t) : (ION_PATH_COLORS[name] || 0xffffff)
        const rgb = [((hex >> 16) & 255) / 255, ((hex >> 8) & 255) / 255, (hex & 255) / 255]
        colors.set(rgb, i * 6); colors.set(rgb, i * 6 + 3)
      }
      lines.geometry.setColors(colors)
    }
  }
  function setPathColorMode(value, settings = {}) {
    const nextMode = value === 'time' ? 'time' : 'species'
    pathColor = { ...pathColor, ...settings, mode: nextMode }
    if (nextMode === 'time' && (settings.lo == null || settings.hi == null)) {
      const range = pathFrameRange()
      if (range) { pathColor.lo = range.min; pathColor.hi = range.max }
    }
    recolorPaths()
  }
  function ensurePaths() {
    if (!batches || pathBatches.length) return
    for (const [name, { positions, ranks, ends, frames }] of batches) {
      if (!positions.length) continue
      const geometry = new LineSegmentsGeometry()
      geometry.setPositions(positions)
      const lines = new LineSegments2(geometry,
        new LineMaterial({ color: 0xffffff, linewidth: width, vertexColors: true }))
      lines.name = `ionPaths-${name}`
      group.add(lines); pathBatches.push({ lines, ranks, ends, frames, name })
    }
    recolorPaths()
    setPercentage(percentage)
  }
  function applyVectorSettings(settings = {}) {
    vectorSettings = { ...vectorSettings, ...settings }
    vectorSettings.density = Math.max(4, Math.min(1000000, Math.trunc(Number(vectorSettings.density) || 14)))
    vectorSettings.magnitude = vectorSettings.magnitude === 'color' ? 'color' : 'size'
    vectorSettings.arrowScale = Math.max(0.25, Math.min(3, Number(vectorSettings.arrowScale) || 1))
    const key = `${vectorSettings.species}:${vectorSettings.density}:${vectorSettings.magnitude}:${vectorSettings.arrowScale}`
    if (data && key !== vectorKey) {
      if (vectorObject) {
        for (const child of [...vectorObject.children]) disposeObject(child)
        vectorObject.removeFromParent()
      }
      const field = ionVectorField(data, vectorSettings.species, vectorSettings.density)
      vectorObject = createVectorArrows(field, vectorSettings.species, vectorSettings.magnitude,
        vectorSettings.arrowScale)
      vectorObject.visible = mode === 'vector-field'
      group.add(vectorObject); vectorKey = key
      return { arrows: field.magnitudes.length, species: vectorSettings.species }
    }
    return { arrows: vectorObject?.children[0]?.geometry?.instanceCount || 0, species: vectorSettings.species }
  }
  function setMode(value) {
    mode = value === 'vector-field' ? 'vector-field' : 'paths'
    if (mode === 'paths') ensurePaths()
    else applyVectorSettings()
    for (const { lines } of pathBatches) lines.visible = mode === 'paths' && lines.geometry.instanceCount > 0
    if (vectorObject) vectorObject.visible = mode === 'vector-field'
  }
  return {
    clear, setWidth, setPercentage, setGrapheneDisplay, setMode, setPathColorMode,
    getPathFrameRange: pathFrameRange,
    setVectorSettings: applyVectorSettings,
    setData(nextData) {
      const nextBatches = ionPathBatches(nextData)
      clearGeometry()
      data = nextData; batches = nextBatches
      if (!active) { active = true; onActiveChange(true) }
      group.matrixAutoUpdate = false
      if (data.origami?.display_transform) group.matrix.fromArray(data.origami.display_transform)
      else group.matrix.identity()
      group.matrixWorldNeedsUpdate = true
      totalPaths = data.paths.length
      if (mode === 'paths') ensurePaths()
      else applyVectorSettings()
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
