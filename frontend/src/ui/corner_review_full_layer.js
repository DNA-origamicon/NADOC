/** Diagnostic Full-style landmarks from the exact A/B atoms, never authoring. */
import * as THREE from 'three'
import { SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK } from '../scene/crossover_connections.js'

export function buildCornerReviewFullLayer(scene, data, strandColors, serials = null) {
  const root = new THREE.Group(); root.name = 'corner-review-atom-landmarks'; scene.add(root)
  const selected = serials && new Set(serials)
  const rows = data.residues.map((row, index) => ({ ...row, index }))
    .filter(row => !selected || row.atom_serials.some(i => selected.has(i)))
  const included = new Set(rows.map(row => row.index))
  const color = row => new THREE.Color(strandColors.get(row.strand_id) ?? '#0070bb')
  function mesh(name, geometry, count) {
    const result = new THREE.InstancedMesh(geometry, new THREE.MeshPhongMaterial(), Math.max(1, count))
    result.name = name; result.count = count; result.frustumCulled = false; root.add(result)
    return result
  }
  const beads = mesh('beads', new THREE.SphereGeometry(.15, 10, 8), rows.length)
  const slabs = mesh('slabs', new THREE.BoxGeometry(SLAB_WIDTH, SLAB_THICK, SLAB_LENGTH), rows.length)
  const links = rows.map(row => [row.backbone_position, row.base_position, color(row)])
  for (const [a, b] of data.backbone_edges) {
    if (included.has(a) && included.has(b)) links.push([
      data.residues[a].backbone_position, data.residues[b].backbone_position, color(data.residues[a]),
    ])
  }
  const rods = mesh('connections', new THREE.CylinderGeometry(.035, .035, 1, 8), links.length)
  const matrix = new THREE.Matrix4(), quaternion = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0)
  rows.forEach((row, i) => {
    beads.setMatrixAt(i, matrix.makeTranslation(...row.backbone_position)); beads.setColorAt(i, color(row))
    const a = row.slab_axes, p = row.base_position
    matrix.set(a[0][0], a[0][1], a[0][2], p[0], a[1][0], a[1][1], a[1][2], p[1],
      a[2][0], a[2][1], a[2][2], p[2], 0, 0, 0, 1)
    slabs.setMatrixAt(i, matrix); slabs.setColorAt(i, color(row))
  })
  links.forEach(([first, second, tint], i) => {
    const a = new THREE.Vector3(...first), b = new THREE.Vector3(...second), delta = b.clone().sub(a)
    const length = delta.length()
    quaternion.identity()
    if (length > 1e-12) quaternion.setFromUnitVectors(up, delta.divideScalar(length))
    matrix.compose(a.add(b).multiplyScalar(.5), quaternion, new THREE.Vector3(1, length, 1))
    rods.setMatrixAt(i, matrix); rods.setColorAt(i, tint)
  })
  for (const item of [beads, slabs, rods]) {
    item.instanceMatrix.needsUpdate = true
    if (item.instanceColor) item.instanceColor.needsUpdate = true
  }
  return { root, dispose() {
    for (const item of [beads, slabs, rods]) { item.geometry.dispose(); item.material.dispose() }
    root.removeFromParent()
  } }
}
