import * as THREE from 'three'

const _finiteVec = v => Number.isFinite(v?.x) && Number.isFinite(v?.y) && Number.isFinite(v?.z)

/**
 * Return the preferred camera-up direction projected into the screen plane.
 *
 * TrackballControls pans vertically along camera.up directly, so camera.up must
 * be perpendicular to the camera-to-target vector. Three.js lookAt() renders a
 * sensible view even when it is not, which otherwise hides the bad basis until
 * the user pans.
 */
export function screenPlaneCameraUp(position, target, preferredUp) {
  const eye = position.clone().sub(target)
  if (!_finiteVec(eye) || eye.lengthSq() < 1e-12) {
    return _finiteVec(preferredUp) && preferredUp.lengthSq() >= 1e-12
      ? preferredUp.clone().normalize()
      : new THREE.Vector3(0, 1, 0)
  }

  eye.normalize()
  const up = _finiteVec(preferredUp) && preferredUp.lengthSq() >= 1e-12
    ? preferredUp.clone()
    : new THREE.Vector3(0, 1, 0)
  up.addScaledVector(eye, -up.dot(eye))

  // A preferred up parallel to the view direction has no screen-plane
  // projection. Pick the world axis least parallel to the view as a fallback.
  if (up.lengthSq() < 1e-12) {
    up.set(Math.abs(eye.y) < 0.9 ? 0 : 1, Math.abs(eye.y) < 0.9 ? 1 : 0, 0)
    up.addScaledVector(eye, -up.dot(eye))
  }
  return up.normalize()
}
