/** Two schematic CPD crosslinks, attached to the live Full-representation slabs. */
import * as THREE from 'three'
import { parseBaseKey } from './base_ref.js'
import { installInstanceAlpha, setInstanceAlpha } from './instance_alpha.js'

export function slabBondEndpoints(a, b) {
  // Put the schematic C5/C6 attachment sites near the middle of each slab,
  // rather than on its outer edge. On a 0.30 nm-wide slab these sites are
  // 0.15 nm apart, keeping the two crosslinks distinct without corner anchoring.
  const sites = matrix => [-0.25, 0.25].map(x =>
    new THREE.Vector3(x, 0, 0).applyMatrix4(matrix))
  const first = sites(a), second = sites(b)
  const distance = (x, y) => x.distanceToSquared(y)
  if (distance(first[0], second[1]) + distance(first[1], second[0]) <
      distance(first[0], second[0]) + distance(first[1], second[1])) second.reverse()
  return first.map((p, i) => [p, second[i]])
}

export function createCpdSlabBonds(design, slabs, resolveIndex) {
  const pairs = (design?.photoproduct_junctions ?? []).filter(p => Object.keys(p.design_coordinates ?? {}).length)
    .map(p => ({ lesion: p, entries: [p.base_key_1, p.base_key_2].map(k => {
      const resolved = resolveIndex(parseBaseKey(k))
      return typeof resolved === 'number' ? { mesh: slabs, index: resolved } : resolved
    }) }))
    .filter(pair => pair.entries.every(e => e?.mesh && Number.isInteger(e.index) && e.index >= 0))
  if (!pairs.length) return null
  const mesh = new THREE.InstancedMesh(new THREE.CylinderGeometry(1, 1, 1, 8),
    new THREE.MeshStandardMaterial({ color: 0xe6a23c, roughness: 0.55 }), pairs.length * 2)
  mesh.name = 'cpdSlabBonds'
  mesh.frustumCulled = false
  mesh.castShadow = true
  const originalGeometry = mesh.geometry
  installInstanceAlpha(mesh)
  originalGeometry.dispose()
  const a = new THREE.Matrix4(), b = new THREE.Matrix4(), matrix = new THREE.Matrix4()
  const y = new THREE.Vector3(0, 1, 0), q = new THREE.Quaternion(), scale = new THREE.Vector3()
  function sync(full = true) {
    mesh.visible = full && pairs.some(p => p.entries.every(e => e.mesh.visible))
    let index = 0
    for (const { entries: [ea, eb], lesion } of pairs) {
      ea.mesh.getMatrixAt(ea.index, a); eb.mesh.getMatrixAt(eb.index, b)
      const alpha = Math.min(ea.mesh._instanceAlpha?.getX(ea.index) ?? 1, eb.mesh._instanceAlpha?.getX(eb.index) ?? 1)
      const valid = ea.mesh.visible && eb.mesh.visible && Math.abs(a.determinant()) > 1e-12 && Math.abs(b.determinant()) > 1e-12
      const ga = lesion.representation_geometry?.[lesion.base_key_1]?.bond_sites
      const gb = lesion.representation_geometry?.[lesion.base_key_2]?.bond_sites
      const endpoints = ga && gb && lesion.display_crosslinks
        ? lesion.display_crosslinks.map(([na, nb]) => [new THREE.Vector3(...ga[na]).applyMatrix4(a), new THREE.Vector3(...gb[nb]).applyMatrix4(b)])
        : slabBondEndpoints(a, b)
      for (const [start, end] of valid ? endpoints : [[y, y], [y, y]]) {
        const delta = end.clone().sub(start), length = delta.length()
        q.setFromUnitVectors(y, length > 1e-9 ? delta.divideScalar(length) : y)
        matrix.compose(start.clone().add(end).multiplyScalar(0.5), q, scale.set(0.025, length, 0.025))
        mesh.setMatrixAt(index, matrix)
        setInstanceAlpha(mesh, index++, valid ? alpha : 0)
      }
    }
    mesh.instanceMatrix.needsUpdate = true
  }
  sync()
  return { mesh, sync }
}
