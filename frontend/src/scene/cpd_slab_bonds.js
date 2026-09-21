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
    .map(p => [p.base_key_1, p.base_key_2].map(k => resolveIndex(parseBaseKey(k))))
    .filter(pair => pair.every(i => Number.isInteger(i) && i >= 0))
  if (!slabs || !pairs.length) return null
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
    mesh.visible = full && slabs.visible
    let index = 0
    for (const [ia, ib] of pairs) {
      slabs.getMatrixAt(ia, a); slabs.getMatrixAt(ib, b)
      const alpha = Math.min(slabs._instanceAlpha?.getX(ia) ?? 1, slabs._instanceAlpha?.getX(ib) ?? 1)
      const valid = Math.abs(a.determinant()) > 1e-12 && Math.abs(b.determinant()) > 1e-12
      for (const [start, end] of valid ? slabBondEndpoints(a, b) : [[y, y], [y, y]]) {
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
