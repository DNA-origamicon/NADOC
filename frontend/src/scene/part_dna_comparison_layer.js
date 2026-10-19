/** Isolated static adapter for the existing native Full renderer. */
import * as THREE from 'three'
import { validateDnaComparisonComponent, validatedDeformationPreviewComponent } from '../features/part_dna_comparison_model.js'
import { decodeDnaComparisonRecordsCopy } from '../features/part_dna_comparison_codec.js'
import { fail } from '../features/part_comparison_validation.js'
import { buildHelixObjects } from './helix_renderer.js'
import { _resetStapleColorPins } from './helix_renderer/palette.js'
import { buildNativeConnectionLines, writeNativeConnectionArc } from './native_connection_lines.js'

const site = n => JSON.stringify([n.helix_id, n.bp_index, n.direction])
const pair = (a, b) => JSON.stringify([site(a), site(b)].sort())

function checkInventory(native, geometry, topology, connections) {
  const expected = new Set(geometry)
  for (const field of ['backboneEntries', 'slabEntries']) {
    const entries = native[field]
    if (entries.length !== geometry.length || new Set(entries.map(e => e.nuc)).size !== expected.size
        || entries.some(entry => !expected.has(entry.nuc))) fail('native renderer omitted occupied DNA')
  }
  const shown = new Set([...native.coneEntries, ...connections].map(connection => pair(connection.fromNuc, connection.toNuc)))
  for (const crossover of topology.crossovers) {
    const endpoint = half => ({ helix_id: half.helix_id, bp_index: half.index, direction: half.strand })
    if (!shown.has(pair(endpoint(crossover.half_a), endpoint(crossover.half_b)))) fail('native renderer omitted an authored crossover')
  }
  for (const ligation of topology.forced_ligations) {
    const endpoint = prefix => ({ helix_id: ligation[`${prefix}_helix_id`],
      bp_index: ligation[`${prefix}_bp`], direction: ligation[`${prefix}_direction`] })
    // Native ligation display follows strand adjacency. Metadata alone cannot
    // invent a connection that the native topology/render owner did not create.
    if (!shown.has(pair(endpoint('three_prime'), endpoint('five_prime')))) fail('native renderer does not represent this authored ligation')
  }
}

export function buildPartDnaComparisonLayer(component, scene, paletteToken = Symbol('private DNA comparison palette')) {
  validateDnaComparisonComponent(component)
  return buildLayer(component, scene, paletteToken, 'privateDnaComparison', 'comparison')
}

export function buildDeformationPreviewLayer(component, scene) {
  validatedDeformationPreviewComponent(component)
  return buildLayer(component, scene, Symbol('private deformation palette'), 'privateDeformationPreview', 'deformationPreview')
}

// The closed adapters above share native construction and resource ownership.
// Neither consults the live store, installs topology or re-evaluates geometry.
function buildLayer(component, scene, paletteToken, name, arcType) {
  const root = new THREE.Group(); root.name = name
  let disposed = false
  function dispose() {
    if (disposed) return
    disposed = true
    const geometries = new Set(), materials = new Set(), instances = new Set()
    root.traverse(node => {
      // installInstanceAlphaGeometry clones the template, but BufferGeometry
      // shares its userData object by reference. Detach that metadata before
      // changing the proven private clone's marker; never mutate the template.
      if (node._instanceAlpha && node.geometry?.getAttribute('instanceAlpha') === node._instanceAlpha)
        node.geometry.userData = { ...node.geometry.userData, shared: false }
      if (node.geometry && !node.geometry.userData?.shared) geometries.add(node.geometry)
      for (const material of Array.isArray(node.material) ? node.material : [node.material]) if (material) materials.add(material)
      if (node.isInstancedMesh) instances.add(node)
    })
    for (const mesh of instances) mesh.dispose()
    for (const geometry of geometries) geometry.dispose()
    for (const material of materials) material.dispose()
    root.removeFromParent(); root.clear()
    // A private Symbol cannot equal any authored/live string design ID.
    _resetStapleColorPins(paletteToken)
  }
  try {
    // Private transport values are copied before a mutable native display owner
    // sees them. No live Design, pose map or store is consulted or installed.
    const topology = structuredClone(component.display_topology)
    const geometry = decodeDnaComparisonRecordsCopy(component.nucleotides)
    // Same raw-response adapter as api/client.js, without its store effects.
    const axes = Object.fromEntries(structuredClone(component.helix_axes).map(axis => [axis.helix_id,
      { start: axis.start, end: axis.end, samples: axis.samples, segments: axis.segments,
        ovhgAxes: axis.ovhg_axes ?? null }]))
    // Static Full-LOD layer: its renderer is never exposed, so hidden
    // cylinder-LOD tubes (~0.26 s on an 18-helix part) are not built.
    const native = buildHelixObjects(geometry, { ...topology, id: paletteToken }, root, {}, [], axes, 'full',
      { curvedCylinders: false })
    if (arcType === 'deformationPreview') native.setAxisShaftMode('deformed')
    const connections = native.getCrossHelixConnections()
    checkInventory(native, geometry, topology, connections)
    root.traverse(node => { if (node.userData.setupOnly) node.visible = false })
    const lines = buildNativeConnectionLines(connections, arcType)
    if (lines) {
      root.add(lines.line)
      for (const arc of connections) {
        const control = new THREE.Vector3((arc.from.x + arc.to.x) * .5,
          (arc.from.y + arc.to.y) * .5, (arc.from.z + arc.to.z) * .5)
        // Exact existing normal 3D (unfold t=0) sampling and line material.
        writeNativeConnectionArc(lines.positions, arc.vertIdx, arc.from, control, arc.to)
      }
      lines.geo.attributes.position.needsUpdate = true
    }
    scene.add(root)
    return { root, dispose }
  } catch (error) { dispose(); throw error }
}
