/** Transient rigid motion of a complete captured native pose, without placement rules. */
import * as THREE from 'three'
import { placementIntegrityFailure, validateNativePlacement } from '../viewer/native_placement.js'

export function nativePoseFrame(nucleotide, normal, tangent = nucleotide.axis_tangent) {
  validateNativePlacement(nucleotide)
  const axis = new THREE.Vector3(...tangent)
  const inward = new THREE.Vector3(...normal)
  if (!Number.isFinite(axis.lengthSq()) || axis.lengthSq() < 1e-16
      || !Number.isFinite(inward.lengthSq())) {
    placementIntegrityFailure(nucleotide, 'animation_frame', { normal, tangent }, 'Animation requires a finite nonzero pose frame')
  }
  axis.normalize()
  inward.addScaledVector(axis, -inward.dot(axis))
  if (inward.lengthSq() < 1e-16) {
    placementIntegrityFailure(nucleotide, 'animation_frame', { normal, tangent }, 'Animation pose frame is degenerate')
  }
  inward.normalize()
  return new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(
    new THREE.Vector3().crossVectors(axis, inward), axis, inward))
}

export function transportNativePose(nucleotide, backbonePosition, orientation = nucleotide.slab_quaternion) {
  validateNativePlacement(nucleotide)
  if (!nucleotide.slab_position || !nucleotide.slab_quaternion) {
    placementIntegrityFailure(nucleotide, 'slab_position', null, 'This animation requires a complete captured slab pose')
  }
  const target = Array.isArray(orientation) ? new THREE.Quaternion(...orientation) : orientation.clone()
  const source = new THREE.Quaternion(...nucleotide.slab_quaternion)
  const delta = target.clone().multiply(source.invert())
  const origin = new THREE.Vector3(...nucleotide.backbone_position)
  const position = new THREE.Vector3(...backbonePosition)
  const point = field => new THREE.Vector3(...nucleotide[field]).sub(origin).applyQuaternion(delta).add(position).toArray()
  const vector = field => new THREE.Vector3(...nucleotide[field]).applyQuaternion(delta).toArray()
  const result = { ...nucleotide, backbone_position: [...backbonePosition],
    base_position: point('base_position'), slab_position: point('slab_position'),
    slab_quaternion: target.toArray(), base_normal: vector('base_normal'), axis_tangent: vector('axis_tangent') }
  if (nucleotide.helical_site) {
    const site = nucleotide.helical_site
    result.helical_site = { ...site,
      axis_point: new THREE.Vector3(...site.axis_point).sub(origin).applyQuaternion(delta).add(position).toArray(),
      radial_hat: new THREE.Vector3(...site.radial_hat).applyQuaternion(delta).toArray() }
  }
  validateNativePlacement(result)
  return result
}
