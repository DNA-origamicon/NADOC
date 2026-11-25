/** Interactive backbone billboards become ordinary spheres in photo mode.
 * Radius, matrices, instance colors, ownership and shared-source placement stay
 * unchanged. Atomistic impostors have a different shader contract and are not
 * opted into this conversion.
 */
import { SphereGeometry } from 'three'

export function photoBackboneRadius(mesh) {
  const material = mesh?.material
  const radius = material?.userData?.impostorRadius
  if (mesh?.name !== 'backboneSpheres' || !material?.userData?.isImpostor ||
      !Number.isFinite(radius) || radius <= 0 ||
      (mesh.userData?.sharedInstanced && !mesh.userData?.applySharedInstancing)) return null
  return radius
}

export function makePhotoBackboneGeometry(mesh) {
  const radius = photoBackboneRadius(mesh)
  return radius == null ? null : new SphereGeometry(radius, 10, 8)
}
