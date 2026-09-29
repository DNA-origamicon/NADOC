// Headless adapter: reuse desktop geometry/preview builders without a WebGL context.
import fs from 'node:fs'
import { buildHelixObjects } from '../src/scene/helix_renderer.js'
import * as THREE from 'three'
import { _hullGeoForSource } from '../src/scene/assembly_hull_geometry.js'
import { buildMrdnaInputPreview } from '../src/ui/mrdna_input_preview.js'
import { buildOxdnaInputPreview } from '../src/ui/oxdna_input_preview.js'
import { initOxdnaInputOverlay } from '../src/scene/oxdna_input_overlay.js'

const { design, geometry, axes, representations } = JSON.parse(fs.readFileSync(0, 'utf8'))
const wanted = name => !representations || representations.includes(name)
const hull = wanted("hull-prism") ? _hullGeoForSource(design, geometry, Object.fromEntries(axes.map(a => [a.helix_id, a]))) : null
const meshData = g => {
  if (!g) return null
  const flat = g.index ? g.toNonIndexed() : g
  // Desktop overhang marker quads are unlit and intentionally omit normals.
  // Native triangles need a geometric normal for the same visible faces.
  if (!flat.attributes.normal) flat.computeVertexNormals()
  return { vertices: Array.from(flat.attributes.position.array), normals: Array.from(flat.attributes.normal.array),
    colors: flat.attributes.color ? Array.from(flat.attributes.color.array) : null }
}
const mrdna = Object.fromEntries(['coarse', 'fine'].filter(resolution => wanted('mrdna-' + resolution)).map(resolution => [resolution, buildMrdnaInputPreview(geometry, resolution)]))
const preview = wanted("oxdna") ? buildOxdnaInputPreview(geometry) : { frames: [], edges: [] }
const overlay = initOxdnaInputOverlay(new THREE.Scene())
overlay.update(preview.frames, preview.edges, 'strand', design)
const oxdna = []
const matrix = new THREE.Matrix4(), color = new THREE.Color()
for (const mesh of overlay.group()?.children ?? []) {
  const primitive = mesh.userData.oxdnaPrimitive
  const entries = []
  for (let i = 0; i < mesh.count; ++i) {
    mesh.getMatrixAt(i, matrix)
    entries.push({ matrix: matrix.toArray(), colors: [] })
  }
  for (const mode of ['strand', 'base', 'cluster', 'strand']) {
    overlay.setColoringMode(mode)
    for (let i = 0; i < mesh.count; ++i) {
      mesh.getColorAt(i, color); entries[i].colors.push(...color.toArray())
    }
  }
  oxdna.push({ primitive, entries, radiusTop: mesh.geometry.parameters.radiusTop,
    radiusBottom: mesh.geometry.parameters.radiusBottom })
}
// Export the actual desktop cylinder meshes, including half cylinders and curved
// tubes. Radius, domain splitting and palette all stay owned by helix_renderer.
const cylinders = []
if (wanted('cylinders')) {
  const customColors = Object.fromEntries(design.strands.filter(s => s.color).map(s => [s.id, parseInt(s.color.replace('#', ''), 16)]))
  for (const group of design.staple_groups ?? []) if (group.color) {
    for (const id of group.strand_ids ?? []) customColors[id] = parseInt(group.color.replace('#', ''), 16)
  }
  const ctrl = buildHelixObjects(geometry, design, new THREE.Scene(), customColors, [],
    Object.fromEntries(axes.map(a => [a.helix_id, a])), 'cylinders')
  ctrl.setDetailLevel(2)
  ctrl.root.updateMatrixWorld(true)
  const meshes = []
  ctrl.root.traverseVisible(mesh => {
    if (!mesh.isMesh || !mesh.geometry?.attributes.position) return
    const count = mesh.isInstancedMesh ? mesh.count : 1
    for (let i = 0; i < count; i++) {
      const transform = mesh.matrixWorld.clone()
      if (mesh.isInstancedMesh) { mesh.getMatrixAt(i, matrix); transform.multiply(matrix) }
      const geo = mesh.geometry.clone().applyMatrix4(transform)
      const data = meshData(geo)
      geo.dispose()
      const entry = { ...data, palettes: [] }
      cylinders.push(entry); meshes.push({ mesh, i, entry })
    }
  })
  for (const mode of ['strand', 'base', 'cluster', 'strand']) {
    ctrl.applyColoring(mode, design)
    for (const { mesh, i, entry } of meshes) {
      if (mesh.isInstancedMesh && mesh.instanceColor) mesh.getColorAt(i, color)
      else color.copy(mesh.material.color)
      entry.palettes.push(...color.toArray())
    }
  }
}
process.stdout.write(JSON.stringify({ cylinders, hull: [meshData(hull?.solid), meshData(hull?.markers)].filter(Boolean), mrdna, oxdna }))
overlay.dispose()
