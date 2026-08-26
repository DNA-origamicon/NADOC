/** Orbitable medoid view for one pooled extra-base position cluster. */
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

const HELIX_COLORS = [0x3b82f6, 0x22d3ee]
const ATOM_COLORS = { "C1'": 0xf8fafc, "C3'": 0xcbd5e1, "C5'": 0xcbd5e1, P: 0xf59e0b }
const CPK_COLORS = { C: 0x606060, N: 0x3050f8, O: 0xff3030, P: 0xff8c00 }
const ATOM_RADII_A = { C: 0.62, N: 0.60, O: 0.57, P: 0.78 }
const SIDE_COLORS = { i: 0xf59e0b, 'i+1': 0x22d3ee }

function disposeTree(root) {
  root?.traverse?.(object => {
    object.geometry?.dispose?.()
    const materials = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of materials) material?.dispose?.()
  })
  root?.removeFromParent?.()
}

function cylinderBetween(a, b, radius, material, radialSegments = 14) {
  const start = new THREE.Vector3(...a)
  const end = new THREE.Vector3(...b)
  const delta = end.clone().sub(start)
  const geometry = new THREE.CylinderGeometry(radius, radius, delta.length(), radialSegments)
  const mesh = new THREE.Mesh(geometry, material)
  mesh.position.copy(start).add(end).multiplyScalar(0.5)
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize())
  return mesh
}

function atomSphere(name, position) {
  const material = new THREE.MeshStandardMaterial({
    color: ATOM_COLORS[name] ?? 0xe879f9,
    roughness: 0.35,
    metalness: 0.05,
  })
  const sphere = new THREE.Mesh(new THREE.SphereGeometry(name === 'P' ? 0.85 : 0.7, 20, 14), material)
  sphere.position.fromArray(position)
  sphere.name = `extra-base-${name}`
  return sphere
}

function baseSlab(atoms, orientation, color = 0xe879f9, prefix = 'extra-base') {
  const c1 = new THREE.Vector3(...atoms["C1'"])
  const center = new THREE.Vector3(...atoms.base)
  const x = center.clone().sub(c1).normalize()
  let z = orientation?.length === 3
    ? new THREE.Vector3(orientation[0][2], orientation[1][2], orientation[2][2]).normalize()
    : new THREE.Vector3(0, 0, 1)
  if (Math.abs(x.dot(z)) > 0.92) z = new THREE.Vector3(0, 1, 0)
  const y = new THREE.Vector3().crossVectors(z, x).normalize()
  z = new THREE.Vector3().crossVectors(x, y).normalize()
  const basis = new THREE.Matrix4().makeBasis(x, y, z)
  const material = new THREE.MeshStandardMaterial({
    color,
    emissive: 0x32113a,
    roughness: 0.4,
  })
  const slab = new THREE.Mesh(new THREE.BoxGeometry(4.6, 2.8, 0.55), material)
  slab.position.copy(center)
  slab.quaternion.setFromRotationMatrix(basis)
  slab.name = `${prefix}-ring`
  return slab
}

function addSchematicNucleotide(group, medoid, accent = 0xa78bfa, prefix = 'extra-base') {
  const atoms = medoid.atoms_A ?? {}
  const bondMaterial = new THREE.MeshStandardMaterial({ color: accent, roughness: 0.4 })
  const chain = ['P', "C5'", "C3'", "C1'", 'base']
  for (let index = 0; index < chain.length - 1; index++) {
    const from = atoms[chain[index]]
    const to = atoms[chain[index + 1]]
    if (from && to) {
      const bond = cylinderBetween(from, to, 0.28, bondMaterial.clone())
      bond.name = `${prefix}-bond-${chain[index]}-${chain[index + 1]}`
      group.add(bond)
    }
  }
  for (const name of ['P', "C5'", "C3'", "C1'"]) {
    if (!atoms[name]) continue
    const sphere = atomSphere(name, atoms[name])
    sphere.name = `${prefix}-${name}`
    group.add(sphere)
  }
  if (atoms.base && atoms["C1'"]) group.add(baseSlab(atoms, medoid.base_orientation, accent, prefix))
}

function addAtomisticNucleotide(group, atomistic, accent = null, prefix = 'atomistic') {
  const byName = Object.fromEntries((atomistic?.atoms ?? []).map(atom => [atom.name, atom]))
  const ribose = new Set(atomistic?.ribose_ring ?? [])
  for (const atom of atomistic?.atoms ?? []) {
    const material = new THREE.MeshStandardMaterial({
      color: accent != null && atom.element === 'C'
        ? accent
        : (CPK_COLORS[atom.element] ?? 0x9ca3af),
      emissive: ribose.has(atom.name) ? 0x24170a : 0x000000,
      roughness: 0.32,
      metalness: 0.02,
    })
    const radius = ATOM_RADII_A[atom.element] ?? 0.6
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(radius, 20, 14), material)
    sphere.position.fromArray(atom.position_A)
    sphere.name = `${prefix}-${atom.name}`
    sphere.userData = {
      atomName: atom.name,
      element: atom.element,
      coordinateSource: atom.coordinate_source,
      ribose: ribose.has(atom.name),
    }
    group.add(sphere)
  }
  for (const [nameA, nameB] of atomistic?.bonds ?? []) {
    const atomA = byName[nameA]
    const atomB = byName[nameB]
    if (!atomA || !atomB) continue
    const riboseBond = ribose.has(nameA) && ribose.has(nameB)
    const bond = cylinderBetween(
      atomA.position_A,
      atomB.position_A,
      riboseBond ? 0.2 : 0.16,
      new THREE.MeshStandardMaterial({
        color: accent ?? (riboseBond ? 0xfbbf24 : 0xb8c0cc),
        roughness: 0.45,
      }),
      12,
    )
    bond.name = `${prefix}-bond-${nameA}-${nameB}`
    group.add(bond)
  }
}

function addDirectedNormal(group, medoid, color, prefix) {
  const orientation = medoid?.base_orientation
  const center = medoid?.atoms_A?.base
  if (!center || !Array.isArray(orientation) || orientation.length !== 3) return
  const direction = new THREE.Vector3(
    Number(orientation[0]?.[2]), Number(orientation[1]?.[2]), Number(orientation[2]?.[2]),
  )
  if (!Number.isFinite(direction.lengthSq()) || direction.lengthSq() < 1e-12) return
  direction.normalize()
  const arrow = new THREE.ArrowHelper(direction, new THREE.Vector3(...center), 8, color, 1.8, 0.8)
  arrow.name = `${prefix}-directed-slab-normal`
  group.add(arrow)
}

function addJunctionContext(group, spacing, activeLevels, levelColors = SIDE_COLORS) {
  const helixMaterial = HELIX_COLORS.map(color => new THREE.MeshStandardMaterial({
    color, transparent: true, opacity: 0.28, roughness: 0.7, depthWrite: false,
  }))
  for (const [index, x] of [-spacing / 2, spacing / 2].entries()) {
    const helix = new THREE.Mesh(new THREE.CylinderGeometry(5, 5, 36, 32), helixMaterial[index])
    helix.position.set(x, 0, 0)
    helix.name = `helix-${index}`
    group.add(helix)
    const axis = cylinderBetween([x, -19, 0], [x, 19, 0], 0.09,
      new THREE.MeshBasicMaterial({ color: HELIX_COLORS[index] }))
    axis.name = `helix-axis-${index}`
    group.add(axis)
  }

  const activeSet = new Set(activeLevels)
  for (const [level, y] of [['i', -1.7], ['i+1', 1.7]]) {
    const active = activeSet.has(level)
    const rung = cylinderBetween(
      [-spacing / 2, y, 0], [spacing / 2, y, 0], active ? 0.32 : 0.13,
      new THREE.MeshBasicMaterial({
        color: active ? levelColors[level] : 0x64748b,
        transparent: !active,
        opacity: active ? 0.95 : 0.45,
      }),
    )
    rung.name = `crossover-${level}`
    group.add(rung)
  }
}

function addPositionSpread(group, cluster, color = 0xfbbf24, name = 'cluster-position-spread') {
  if (cluster?.center_A?.length !== 3) return
  const center = new THREE.Mesh(
    new THREE.SphereGeometry(Math.max(0.5, Number(cluster.spread_A) || 0.5), 18, 12),
    new THREE.MeshBasicMaterial({ color, wireframe: true, transparent: true, opacity: 0.8 }),
  )
  center.position.fromArray(cluster.center_A)
  center.name = name
  group.add(center)
}

function addFrameAxes(group, spacing) {
  const axes = new THREE.AxesHelper(8)
  axes.name = 'helix-pair-frame-axes'
  axes.position.set(-spacing / 2 - 7, -14, 0)
  group.add(axes)
}

export function buildExtraBaseClusterGroup(cluster, side, representation = 'schematic') {
  const group = new THREE.Group()
  group.name = `extra-base-cluster-${side}`
  const medoid = cluster?.medoid ?? {}
  const spacing = Number.isFinite(Number(medoid.interhelix_A)) ? Number(medoid.interhelix_A) : 25

  addJunctionContext(group, spacing, [side], { ...SIDE_COLORS, [side]: 0xf59e0b })

  const resolvedRepresentation = representation === 'atomistic' && medoid.atomistic
    ? 'atomistic'
    : 'schematic'
  if (resolvedRepresentation === 'atomistic') addAtomisticNucleotide(group, medoid.atomistic)
  else addSchematicNucleotide(group, medoid)

  addPositionSpread(group, cluster)
  addFrameAxes(group, spacing)
  group.userData = { side, spacing_A: spacing, medoidFrame: medoid.frame, representation: resolvedRepresentation }
  return group
}

export function buildExtraBaseComparisonGroup(clusterI, clusterI1, representation = 'schematic') {
  const group = new THREE.Group()
  group.name = 'extra-base-cluster-comparison'
  const entries = [['i', clusterI], ['i+1', clusterI1]]
  const spacings = entries.map(([, cluster]) => Number(cluster?.medoid?.interhelix_A))
    .filter(Number.isFinite)
  const spacing = spacings.length ? spacings.reduce((sum, value) => sum + value, 0) / spacings.length : 25
  addJunctionContext(group, spacing, ['i', 'i+1'])

  const atomisticReady = entries.every(([, cluster]) => Boolean(cluster?.medoid?.atomistic))
  const resolvedRepresentation = representation === 'atomistic' && atomisticReady
    ? 'atomistic'
    : 'schematic'
  for (const [side, cluster] of entries) {
    const medoid = cluster?.medoid ?? {}
    if (resolvedRepresentation === 'atomistic') {
      addAtomisticNucleotide(group, medoid.atomistic, SIDE_COLORS[side], `atomistic-${side}`)
    } else {
      addSchematicNucleotide(group, medoid, SIDE_COLORS[side], `extra-base-${side}`)
    }
    addPositionSpread(group, cluster, SIDE_COLORS[side], `cluster-position-spread-${side}`)
  }
  addFrameAxes(group, spacing)

  const c1I = clusterI?.medoid?.atoms_A?.["C1'"]
  const c1I1 = clusterI1?.medoid?.atoms_A?.["C1'"]
  const c1SeparationA = c1I && c1I1
    ? new THREE.Vector3(...c1I).distanceTo(new THREE.Vector3(...c1I1))
    : null
  group.userData = {
    spacing_A: spacing,
    representation: resolvedRepresentation,
    c1Separation_A: c1SeparationA,
    medoidFrames: entries.map(([, cluster]) => cluster?.medoid?.frame),
  }
  return group
}

/** Build one real-frame local junction view from an on-demand sample-audit group. */
export function buildExtraBaseSampleGroup(records = [], representation = 'atomistic') {
  const group = new THREE.Group()
  group.name = 'extra-base-sample-group'
  const spacings = records.map(record => Number(record?.interhelix_A)).filter(Number.isFinite)
  const spacing = spacings.length
    ? spacings.reduce((sum, value) => sum + value, 0) / spacings.length
    : 25
  const activeSides = [...new Set(records.map(record => record.side).filter(side => side === 'i' || side === 'i+1'))]
  addJunctionContext(group, spacing, activeSides)
  records.forEach((record, index) => {
    const color = SIDE_COLORS[record.side] ?? [0xa371f7, 0x3fb950, 0xf85149][index % 3]
    const prefix = `sample-${record.side}-${record.crossover_id}-${record.insert_k}`
    if (representation === 'atomistic' && record.atomistic) {
      addAtomisticNucleotide(group, record.atomistic, color, prefix)
    } else {
      addSchematicNucleotide(group, record, color, prefix)
    }
    addDirectedNormal(group, record, color, prefix)
  })
  addFrameAxes(group, spacing)
  group.userData = {
    spacing_A: spacing,
    representation,
    frame: records[0]?.frame,
    crossoverIds: [...new Set(records.map(record => record.crossover_id))],
  }
  return group
}

/** Orbitable viewer for one or both members of a real sampled reciprocal pair. */
export function createExtraBaseSampleViewer(container, { records = [] } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setClearColor(0x070b12, 1)
  container.appendChild(renderer.domElement)
  const scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xffffff, 0x111827, 1.35))
  const key = new THREE.DirectionalLight(0xffffff, 1.5)
  key.position.set(30, 35, 45)
  scene.add(key)
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 300)
  camera.position.set(38, 26, 48)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.target.set(0, 0, -2)
  let representation = 'atomistic'
  let sampleGroup = buildExtraBaseSampleGroup(records, representation)
  scene.add(sampleGroup)
  let alive = true
  let raf = null
  const resize = () => {
    const width = Math.max(300, container.clientWidth || 620)
    const height = Math.max(300, Math.min(460, Math.round(width * 0.58)))
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
  }
  const observer = new ResizeObserver(resize)
  observer.observe(container)
  resize()
  const rebuild = () => {
    disposeTree(sampleGroup)
    sampleGroup = buildExtraBaseSampleGroup(records, representation)
    scene.add(sampleGroup)
  }
  const render = () => {
    if (!alive) return
    controls.update()
    renderer.render(scene, camera)
    raf = requestAnimationFrame(render)
  }
  render()
  return {
    setRepresentation(next) {
      representation = next === 'schematic' ? 'schematic' : 'atomistic'
      rebuild()
    },
    resetView() {
      camera.position.set(38, 26, 48)
      controls.target.set(0, 0, -2)
      controls.update()
    },
    dispose() {
      alive = false
      if (raf != null) cancelAnimationFrame(raf)
      observer.disconnect()
      controls.dispose()
      disposeTree(sampleGroup)
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
}

/** Create a responsive, orbitable viewer. Returns ``setCluster`` and ``dispose``. */
export function createExtraBaseClusterViewer(container, { side, clusters, initialIndex = 0 } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setClearColor(0x070b12, 1)
  container.appendChild(renderer.domElement)

  const scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xffffff, 0x111827, 1.35))
  const key = new THREE.DirectionalLight(0xffffff, 1.5)
  key.position.set(30, 35, 45)
  scene.add(key)
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 300)
  camera.position.set(38, 26, 48)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.target.set(0, 0, -2)

  let clusterGroup = null
  let clusterIndex = initialIndex
  let representation = 'schematic'
  let alive = true
  let raf = null
  const resize = () => {
    const width = Math.max(280, container.clientWidth || 520)
    const height = Math.max(260, Math.min(390, Math.round(width * 0.62)))
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
  }
  const observer = new ResizeObserver(resize)
  observer.observe(container)
  resize()

  function setCluster(index) {
    clusterIndex = index
    disposeTree(clusterGroup)
    clusterGroup = buildExtraBaseClusterGroup(clusters?.[clusterIndex], side, representation)
    scene.add(clusterGroup)
  }
  function setRepresentation(nextRepresentation) {
    representation = nextRepresentation === 'atomistic' ? 'atomistic' : 'schematic'
    setCluster(clusterIndex)
  }
  setCluster(initialIndex)

  const render = () => {
    if (!alive) return
    controls.update()
    renderer.render(scene, camera)
    raf = requestAnimationFrame(render)
  }
  render()

  return {
    setCluster,
    setRepresentation,
    dispose() {
      alive = false
      if (raf != null) cancelAnimationFrame(raf)
      observer.disconnect()
      controls.dispose()
      disposeTree(clusterGroup)
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
}

/** One orbitable frame containing selected medoids from both reciprocal HJ sides. */
export function createExtraBaseComparisonViewer(container, {
  sideI,
  sideI1,
  initialIndices = { i: 0, 'i+1': 0 },
} = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setClearColor(0x070b12, 1)
  container.appendChild(renderer.domElement)

  const scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xffffff, 0x111827, 1.35))
  const key = new THREE.DirectionalLight(0xffffff, 1.5)
  key.position.set(30, 35, 45)
  scene.add(key)
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 300)
  camera.position.set(38, 26, 48)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.target.set(0, 0, -2)

  let clusterGroup = null
  let alive = true
  let raf = null
  let representation = 'schematic'
  let indices = { i: Number(initialIndices.i || 0), 'i+1': Number(initialIndices['i+1'] || 0) }
  const resize = () => {
    const width = Math.max(320, container.clientWidth || 900)
    const height = Math.max(320, Math.min(520, Math.round(width * 0.42)))
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
  }
  const observer = new ResizeObserver(resize)
  observer.observe(container)
  resize()

  function rebuild() {
    disposeTree(clusterGroup)
    clusterGroup = buildExtraBaseComparisonGroup(
      sideI?.clusters?.[indices.i],
      sideI1?.clusters?.[indices['i+1']],
      representation,
    )
    scene.add(clusterGroup)
  }
  function setClusters(nextIndices) {
    indices = { ...indices, ...nextIndices }
    rebuild()
  }
  function setRepresentation(nextRepresentation) {
    representation = nextRepresentation === 'atomistic' ? 'atomistic' : 'schematic'
    rebuild()
  }
  rebuild()

  const render = () => {
    if (!alive) return
    controls.update()
    renderer.render(scene, camera)
    raf = requestAnimationFrame(render)
  }
  render()

  return {
    setClusters,
    setRepresentation,
    dispose() {
      alive = false
      if (raf != null) cancelAnimationFrame(raf)
      observer.disconnect()
      controls.dispose()
      disposeTree(clusterGroup)
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
}
