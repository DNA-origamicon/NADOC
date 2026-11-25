import * as THREE from 'three'

const _finiteVec = v => Number.isFinite(v.x) && Number.isFinite(v.y) && Number.isFinite(v.z)

/** Compute a finite camera pose for a box, recovering from a poisoned camera/target. */
export function fitViewPose(box, cameraPosition, controlsTarget, fovDeg, aspect = 1) {
  if (!box || box.isEmpty()) return null
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  if (!_finiteVec(center) || !_finiteVec(size)) return null
  // Enclose every corner for any orbit orientation, using the narrower frustum.
  const radius = size.length() * 0.5
  const vertical = fovDeg * Math.PI / 360
  const horizontal = Math.atan(Math.tan(vertical) * aspect)
  const dist = Math.max(1, radius / Math.sin(Math.min(vertical, horizontal)) * 1.15)
  let dir = cameraPosition.clone().sub(controlsTarget)
  if (!_finiteVec(dir) || dir.lengthSq() < 1e-12) dir = new THREE.Vector3(0, 0, 1)
  else dir.normalize()
  return { target: center, position: center.clone().addScaledVector(dir, dist) }
}

/** Initial opening should not hide an elongated assembly behind its end face.
 * Manual Fit continues to preserve the user's view direction. Only strongly
 * elongated, nearly end-on initial views choose a diagonal observation angle.
 */
export function fitOpeningViewPose(box, cameraPosition, controlsTarget, fovDeg, aspect = 1) {
  if (!box || box.isEmpty()) return null
  const size = box.getSize(new THREE.Vector3())
  const lengths = [size.x, size.y, size.z]
  const longest = lengths.indexOf(Math.max(...lengths))
  const other = lengths.filter((_, i) => i !== longest)
  const direction = cameraPosition.clone().sub(controlsTarget).normalize()
  const component = [direction.x, direction.y, direction.z][longest]
  if (lengths[longest] > 4 * Math.max(...other, 1e-6) && Math.abs(component) > .95) {
    const diagonal = new THREE.Vector3(1, .65, 1).normalize()
    return fitViewPose(box, controlsTarget.clone().add(diagonal), controlsTarget, fovDeg, aspect)
  }
  return fitViewPose(box, cameraPosition, controlsTarget, fovDeg, aspect)
}
