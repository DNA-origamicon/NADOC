/** Pure native display construction; caller owns materials and geometry. */
import * as THREE from 'three'

const GOLD = 0xeac13b

export function nanoparticlePoseMatrix(particle) {
  const values = particle?.pose?.values ?? particle?.pose
  const matrix = new THREE.Matrix4()
  if (Array.isArray(values) && values.length === 16) matrix.fromArray(values).transpose()
  return matrix
}

export function createNanoparticleMaterial(particle, { selected = false, fluorescence = false } = {}) {
  if (particle.kind === 'quantum_dot') {
    const color = particle.quantum_dot?.display_color ?? '#58d65d'
    return new THREE.MeshPhysicalMaterial({ color, metalness: 0, roughness: 0.3, clearcoat: 0.35,
      emissive: color, emissiveIntensity: fluorescence ? 1.5 : selected ? 0.5 : 0.12, toneMapped: !fluorescence })
  }
  // Same editor material; photo mode supplies its independent studio material.
  return new THREE.MeshPhysicalMaterial({ color: GOLD, metalness: 0.575, roughness: 0.34, clearcoat: 0.265,
    clearcoatRoughness: 0.26, envMapIntensity: 0.975, emissive: GOLD, emissiveIntensity: selected ? 0.35 : 0.15 })
}

export function createNanoparticleMesh(particle, material) {
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(particle.diameter_nm / 2, 48, 32), material)
  mesh.name = `${particle.kind === 'quantum_dot' ? 'quantum-dot' : 'gold-nanosphere'}:${particle.id}`
  mesh.userData.nanoparticleId = particle.id
  mesh.userData.nanoparticleKind = particle.kind
  if (particle.kind !== 'quantum_dot') mesh.userData.photoMaterialKind = 'gold-nanoparticle'
  mesh.applyMatrix4(nanoparticlePoseMatrix(particle))
  return mesh
}
