import * as THREE from 'three'
import { requireMappedNativePose } from '../viewer/native_placement.js'

/** Translate measured extension slabs with the unfold bead, preserving registration. */
export function unfoldExtensionSlabs(slabs, beadFor, straightPositions, dimensions) {
  const matrix = new THREE.Matrix4(), center = new THREE.Vector3(), quaternion = new THREE.Quaternion()
  const scale = new THREE.Vector3(dimensions.length, dimensions.width, dimensions.thickness)
  const moved = []
  for (const slab of slabs) {
    const n = slab.nuc
    if (!n.extension_id) continue
    const bead = beadFor(n)
    if (!bead) continue
    const straight = straightPositions?.get(`${n.helix_id}:${n.bp_index}:${n.direction}`)
    const pose = straight ? requireMappedNativePose(straight, n) : n
    center.fromArray(pose.slab_position).sub(new THREE.Vector3(...pose.backbone_position)).add(bead.pos)
    quaternion.fromArray(pose.slab_quaternion)
    slab.instMesh.setMatrixAt(slab.id, matrix.compose(center, quaternion, scale))
    slab.instMesh.instanceMatrix.needsUpdate = true
    slab.bbPos.copy(bead.pos)
    moved.push(slab)
  }
  return moved
}
