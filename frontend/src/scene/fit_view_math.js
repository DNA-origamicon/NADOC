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
