import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'
import { buildCrossoverConnections } from './crossover_connections.js'
import { buildNativeConnectionLines, writeNativeConnectionArc } from './native_connection_lines.js'
import { _resetStapleColorPins } from './helix_renderer/palette.js'

function disposeRoot(root) {
  const geometry = new Set(), materials = new Set()
  root.traverse(node => {
    if (node._instanceAlpha && node.geometry?.getAttribute('instanceAlpha') === node._instanceAlpha)
      node.geometry.userData = { ...node.geometry.userData, shared: false }
    if (node.geometry && !node.geometry.userData?.shared) geometry.add(node.geometry)
    for (const value of Array.isArray(node.material) ? node.material : [node.material]) if (value) materials.add(value)
    if (node.isInstancedMesh) node.dispose()
  })
  geometry.forEach(value => value.dispose()); materials.forEach(value => value.dispose())
  root.removeFromParent(); root.clear()
}

function addPlane(root, guide) {
  const center = new THREE.Vector3(...guide.center_nm)
  const radius = Math.max(2, ...guide.cuts.flatMap(cut => [cut.incoming_nm, cut.outgoing_nm])
    .map(point => new THREE.Vector3(...point).distanceTo(center))) + 2
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(2 * radius, 2 * radius),
    new THREE.MeshBasicMaterial({ color: 0x9fc9ed, side: THREE.DoubleSide,
      transparent: true, opacity: .12, depthWrite: false }))
  plane.name = 'corner-plane'
  plane.position.copy(center)
  plane.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...guide.plane_normal))
  plane.add(new THREE.LineSegments(new THREE.EdgesGeometry(plane.geometry),
    new THREE.LineBasicMaterial({ color: 0x9fc9ed, transparent: true, opacity: .65 })))
  root.add(plane)
}

/** Own only private meshes. The live Design and its geometry remain untouched. */
export function createCornerPreview({ scene, getLiveRoot }) {
  let root = null, live = null, wasVisible = false, palette = null, lastGuide = null
  function clear() {
    if (root) disposeRoot(root)
    if (palette) _resetStapleColorPins(palette)
    root = null; palette = null; lastGuide = null
    if (live && getLiveRoot() === live) live.visible = wasVisible
    live = null
  }
  function install(next, hideLive) {
    clear(); root = next; scene.add(root)
    if (hideLive) { live = getLiveRoot(); wasVisible = live?.visible ?? false; if (live) live.visible = false }
  }
  function guide(value) {
    const next = new THREE.Group(); next.name = 'corner-cylinder-preview'
    try {
      for (const [field, color] of [['incoming_path_nm', 0x318acb], ['outgoing_path_nm', 0xe7a346]]) {
        const matrices = [], pose = new THREE.Object3D()
        for (const cut of value.cuts) {
          const points = cut[field].map(point => new THREE.Vector3(...point))
          for (let i = 1; i < points.length; i++) {
            const delta = points[i].clone().sub(points[i - 1]), length = delta.length()
            if (length < 1e-9) continue
            pose.position.copy(points[i]).add(points[i - 1]).multiplyScalar(.5)
            pose.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize())
            pose.scale.set(1, length, 1); pose.updateMatrix(); matrices.push(pose.matrix.clone())
          }
        }
        if (matrices.length) {
          const mesh = new THREE.InstancedMesh(new THREE.CylinderGeometry(1, 1, 1, 10),
            new THREE.MeshStandardMaterial({ color, transparent: true, opacity: .65 }), matrices.length)
          matrices.forEach((matrix, index) => mesh.setMatrixAt(index, matrix))
          mesh.instanceMatrix.needsUpdate = true; next.add(mesh)
        }
      }
      addPlane(next, value)
      install(next, true); lastGuide = value
    } catch (error) { disposeRoot(next); throw error }
  }
  function full(component) {
    if (component?.component_kind !== 'corner-preview-dna' || component.component_version !== 1)
      throw new Error('Unsupported Corner preview display.')
    const next = new THREE.Group(); next.name = 'corner-full-preview'
    const guide = lastGuide
    const token = Symbol('corner preview palette')
    try {
      const topology = structuredClone(component.display_topology), geometry = structuredClone(component.nucleotides)
      const axes = Object.fromEntries(component.helix_axes.map(axis => [axis.helix_id,
        { start: axis.start, end: axis.end, samples: axis.samples, segments: axis.segments, ovhgAxes: axis.ovhg_axes }]))
      const native = buildHelixObjects(geometry, { ...topology, id: token }, next, {}, [], axes, 'full',
        { curvedCylinders: false, axisMeshes: false })
      const extras = buildCrossoverConnections(topology, geometry, native.getPaletteColors(), {})
      if (extras) next.add(extras.group)
      const inserted = new Set((component.seam_inserts ?? []).map(row => row.connection_id))
      for (const id of inserted) if (!extras?.arcData.some(arc => arc.xoId === id))
        throw new Error('Corner preview omitted an unpaired seam.')
      const site = nuc => JSON.stringify([nuc.helix_id, nuc.bp_index, nuc.direction])
      const pair = (a, b) => JSON.stringify([site(a), site(b)].sort())
      // Native strand continuations carry endpoint identities, not crossover
      // record IDs. Inserted seams already own their complete connector chain.
      const insertedPairs = new Set((extras?.arcData ?? []).map(arc => pair(arc.nucA, arc.nucB)))
      const connections = native.getCrossHelixConnections().filter(arc => !insertedPairs.has(pair(arc.fromNuc, arc.toNuc)))
      const lines = buildNativeConnectionLines(connections, 'corner')
      if (lines) {
        next.add(lines.line)
        for (const arc of connections) writeNativeConnectionArc(lines.positions, arc.vertIdx, arc.from,
          arc.from.clone().add(arc.to).multiplyScalar(.5), arc.to)
        lines.geo.attributes.position.needsUpdate = true
      }
      next.traverse(node => { if (node.userData.setupOnly) node.visible = false })
      if (guide) addPlane(next, guide)
      install(next, true); palette = token; lastGuide = guide
    } catch (error) { disposeRoot(next); _resetStapleColorPins(token); throw error }
  }
  return { guide, full, clear, dispose: clear }
}
