/** Atom-index PEG representation, using the shared atomistic radius catalogue. */
import * as THREE from 'three'
import { ELEMENTS, DEFAULT_ELEMENT, BALL_RADIUS, BOND_RADIUS } from './atomistic_renderer/atom_palette.js'

export function pegMoleculeNodes({ xyz, indices, colors, elements, bonds, representation }) {
  const nodes = [], atomistic = ['vdw', 'ballstick', 'stick', 'beads'].includes(representation)
  if (!atomistic) {
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(indices.flatMap(i => xyz[i]), 3))
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
    nodes.push(new THREE.Points(geometry, new THREE.PointsMaterial({ vertexColors: true, size: .085 })))
  } else {
    const bonded = new Set(bonds.flat())
    const spheres = indices.map((i, colorIndex) => ({ i, colorIndex })).filter(({ i }) => representation !== 'stick' || !bonded.has(i))
    const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 12, 8), new THREE.MeshStandardMaterial({ roughness: .6 }), spheres.length)
    const transform = new THREE.Object3D(), color = new THREE.Color()
    spheres.forEach(({ i, colorIndex }, n) => {
      const radius = representation === 'vdw' ? (ELEMENTS[elements[i]] || DEFAULT_ELEMENT).vdw : BALL_RADIUS
      transform.position.set(...xyz[i]); transform.scale.setScalar(radius); transform.updateMatrix()
      mesh.setMatrixAt(n, transform.matrix); mesh.setColorAt(n, color.fromArray(colors, colorIndex*3))
    })
    if (spheres.length) nodes.push(mesh)
    else { mesh.geometry.dispose(); mesh.material.dispose(); mesh.dispose() }
  }
  if (representation === 'vdw') return nodes
  if (['ballstick', 'stick'].includes(representation)) {
    const mesh = new THREE.InstancedMesh(new THREE.CylinderGeometry(1, 1, 1, 8), new THREE.MeshStandardMaterial({ roughness: .6 }), bonds.length)
    const transform = new THREE.Object3D(), a = new THREE.Vector3(), b = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0)
    const colorIndices = new Map(indices.map((i, n) => [i, n])), color = new THREE.Color(), other = new THREE.Color()
    bonds.forEach(([i, j], n) => {
      a.set(...xyz[i]); b.set(...xyz[j]); transform.position.copy(a).add(b).multiplyScalar(.5)
      const length = a.distanceTo(b)
      transform.quaternion.setFromUnitVectors(up, b.sub(a).normalize()); transform.scale.set(BOND_RADIUS, length, BOND_RADIUS); transform.updateMatrix()
      mesh.setMatrixAt(n, transform.matrix)
      color.fromArray(colors, colorIndices.get(i)*3); other.fromArray(colors, colorIndices.get(j)*3)
      mesh.setColorAt(n, color.lerp(other, .5))
    })
    nodes.push(mesh)
  } else {
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(bonds.flatMap(([a, b]) => [...xyz[a], ...xyz[b]]), 3))
    nodes.push(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: '#a7b1c2' })))
  }
  return nodes
}
