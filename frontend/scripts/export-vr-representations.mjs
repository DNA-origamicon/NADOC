// Headless adapter: reuse desktop geometry/preview builders without a WebGL context.
import fs from 'node:fs'
import * as THREE from 'three'
import { _hullGeoForSource } from '../src/scene/assembly_hull_geometry.js'
import { buildMrdnaInputPreview } from '../src/ui/mrdna_input_preview.js'
import { buildOxdnaInputPreview } from '../src/ui/oxdna_input_preview.js'
import { initOxdnaInputOverlay } from '../src/scene/oxdna_input_overlay.js'

const { design, geometry, axes } = JSON.parse(fs.readFileSync(0, 'utf8'))
const hull = _hullGeoForSource(design, geometry, Object.fromEntries(axes.map(a => [a.helix_id, a])))
const meshData = g => {
  if (!g) return null
  const flat = g.index ? g.toNonIndexed() : g
  return { vertices: Array.from(flat.attributes.position.array), normals: Array.from(flat.attributes.normal.array),
    colors: flat.attributes.color ? Array.from(flat.attributes.color.array) : null }
}
const mrdna = Object.fromEntries(['coarse', 'fine'].map(resolution => [resolution, buildMrdnaInputPreview(geometry, resolution)]))
const preview = buildOxdnaInputPreview(geometry)
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
process.stdout.write(JSON.stringify({ hull: [meshData(hull?.solid), meshData(hull?.markers)].filter(Boolean), mrdna, oxdna }))
overlay.dispose()
