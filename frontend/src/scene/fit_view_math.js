import * as THREE from 'three'

const _finiteVec = v => Number.isFinite(v.x) && Number.isFinite(v.y) && Number.isFinite(v.z)

/** Compute a finite camera pose for a box, recovering from a poisoned camera/target. */
export function fitViewPose(box, cameraPosition, controlsTarget, fovDeg) {
  if (!box || box.isEmpty()) return null
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  if (!_finiteVec(center) || !_finiteVec(size)) return null
  const radius = Math.max(size.x, size.y, size.z) * 0.5
  const dist = Math.max(1, (radius / Math.sin((fovDeg * 0.5) * Math.PI / 180)) * 1.15)
  let dir = cameraPosition.clone().sub(controlsTarget)
  if (!_finiteVec(dir) || dir.lengthSq() < 1e-12) dir = new THREE.Vector3(0, 0, 1)
  else dir.normalize()
  return { target: center, position: center.clone().addScaledVector(dir, dist) }
}
