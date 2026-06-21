/**
 * Camera axis-snapping helpers for the 'n' shortcut.
 *
 * `nearestWorkspaceAxis` picks, of the six signed world axes (±X, ±Y, ±Z), the
 * one closest to the current view-from direction (target→camera), so pressing
 * 'n' rolls the camera onto the nearest orthographic-ish view rather than a
 * fixed face. The up convention matches the view-cube faces (view_cube.js):
 * X/Z views use +Y up, Y views use +Z up.
 *
 * `signedAlong` flips an arbitrary plane normal to the hemisphere the camera is
 * already on, so snapping to a lattice-grid normal doesn't whip the camera 180°
 * to the back face.
 */
import * as THREE from 'three'

// Six signed world axes + the camera-up to use when viewing along each.
const AXES = [
  { normal: new THREE.Vector3( 1,  0,  0), up: new THREE.Vector3(0, 1, 0) },
  { normal: new THREE.Vector3(-1,  0,  0), up: new THREE.Vector3(0, 1, 0) },
  { normal: new THREE.Vector3( 0,  1,  0), up: new THREE.Vector3(0, 0, 1) },
  { normal: new THREE.Vector3( 0, -1,  0), up: new THREE.Vector3(0, 0, 1) },
  { normal: new THREE.Vector3( 0,  0,  1), up: new THREE.Vector3(0, 1, 0) },
  { normal: new THREE.Vector3( 0,  0, -1), up: new THREE.Vector3(0, 1, 0) },
]

/**
 * Nearest signed world axis to `fromDir` (the target→camera direction).
 * @param {THREE.Vector3} fromDir — need not be normalized.
 * @returns {{ normal: THREE.Vector3, up: THREE.Vector3 }} fresh clones.
 */
export function nearestWorkspaceAxis(fromDir) {
  const d = fromDir.clone().normalize()
  let best = AXES[0]
  let bestDot = -Infinity
  for (const a of AXES) {
    const dot = a.normal.dot(d)
    if (dot > bestDot) { bestDot = dot; best = a }
  }
  return { normal: best.normal.clone(), up: best.up.clone() }
}

/**
 * Return `normal` flipped to the same hemisphere as `fromDir`, so a camera
 * already in front of a plane stays in front when it snaps to that plane's
 * normal. Ties (camera in the plane) keep the given orientation.
 * @returns {THREE.Vector3} a fresh vector.
 */
export function signedAlong(normal, fromDir) {
  const n = normal.clone().normalize()
  return n.dot(fromDir) < 0 ? n.negate() : n
}
