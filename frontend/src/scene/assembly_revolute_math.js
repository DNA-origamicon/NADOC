/**
 * Pure Three.js math for revolute joint operations.
 *
 * Extracted from assembly_joint_renderer.js private helpers so they can be
 * reused for instance-level drag without duplicating code.
 */

import * as THREE from 'three'

const _Y = new THREE.Vector3(0, 1, 0)
const _Z = new THREE.Vector3(0, 0, 1)

/**
 * Build a stable reference vector perpendicular to axisDir.
 * Prefers Y-axis, falls back to Z when axis is nearly parallel to Y.
 */
export function makeRefVec(axisDir) {
  const tmp = Math.abs(axisDir.dot(_Y)) < 0.9 ? _Y.clone() : _Z.clone()
  return tmp.addScaledVector(axisDir, -tmp.dot(axisDir)).normalize()
}

/**
 * Intersect the camera ray with the plane perpendicular to axisDir through axisOrigin.
 *
 * @param {THREE.Raycaster} rc
 * @param {MouseEvent}      e
 * @param {THREE.Camera}    camera
 * @param {HTMLElement}     canvas
 * @param {THREE.Vector3}   axisDir     (unit vector)
 * @param {THREE.Vector3}   axisOrigin
 * @returns {THREE.Vector3|null}  world-space hit point, or null on miss
 */
export function ringPlaneHit(rc, e, camera, canvas, axisDir, axisOrigin) {
  const rect = canvas.getBoundingClientRect()
  const ndc  = new THREE.Vector2(
    ((e.clientX - rect.left) / rect.width)  * 2 - 1,
    -((e.clientY - rect.top)  / rect.height) * 2 + 1,
  )
  rc.setFromCamera(ndc, camera)
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(axisDir, axisOrigin)
  const hit   = new THREE.Vector3()
  return rc.ray.intersectPlane(plane, hit) ? hit : null
}

/**
 * Compute the signed angle (radians) of worldPt around the axis relative to refVec.
 * Uses atan2(cross.dot(axisDir), refVec.dot(v)).
 */
export function angleInRing(worldPt, axisOrigin, axisDir, refVec) {
  const v = worldPt.clone().sub(axisOrigin)
  v.addScaledVector(axisDir, -v.dot(axisDir))
  if (v.lengthSq() < 1e-12) return 0
  v.normalize()
  const cross = new THREE.Vector3().crossVectors(refVec, v)
  return Math.atan2(cross.dot(axisDir), refVec.dot(v))
}

/**
 * Compute a new Three.js Matrix4 for a child instance after a prismatic (linear) translation.
 *
 * position = base_position + axis_direction * distance
 * rotation = base_rotation (unchanged)
 *
 * @param {number[]}  baseValues  NADOC row-major float[16]
 * @param {number[]}  axisDir     [x, y, z] world-space translation axis
 * @param {number}    distance    signed distance along axis in world units
 * @returns {THREE.Matrix4}
 */
export function computePrismaticTransform(baseValues, axisDir, distance) {
  const baseMat = new THREE.Matrix4().fromArray(baseValues).transpose()
  const axis    = new THREE.Vector3(...axisDir).normalize()
  const basePos = new THREE.Vector3().setFromMatrixPosition(baseMat)
  const result  = baseMat.clone()
  result.setPosition(basePos.clone().addScaledVector(axis, distance))
  return result
}

/**
 * Clamp a quaternion's twist component around `axisDir` to the angular range
 * `[minAngleRad, maxAngleRad]`.  Mirrors the swing–twist decomposition used by
 * the backend `_optimize_chord` linker-relax search so that the gizmo, the
 * animation interpolator, and the optimizer all enforce the same mechanical
 * limits set on a `ClusterJoint`.
 *
 * Decomposition:  quat = swingQ × twistQ  where twistQ is the rotation around
 * `axisDir`.  We extract the signed twist angle, clamp it, and recompose.
 * Returns a *new* THREE.Quaternion (input is not mutated).
 *
 * @param {THREE.Quaternion} quat
 * @param {THREE.Vector3}    axisDir       unit vector
 * @param {number}           minAngleRad
 * @param {number}           maxAngleRad
 * @returns {THREE.Quaternion}
 */
export function clampQuatTwist(quat, axisDir, minAngleRad, maxAngleRad) {
  // Project quat.xyz onto axisDir to find the twist component.
  const dot = quat.x * axisDir.x + quat.y * axisDir.y + quat.z * axisDir.z
  const twistVec = axisDir.clone().multiplyScalar(dot)
  const twistQ = new THREE.Quaternion(twistVec.x, twistVec.y, twistVec.z, quat.w)
  if (twistQ.lengthSq() < 1e-20) return quat.clone()
  twistQ.normalize()

  // Signed twist angle around axisDir, normalised to (-π, π].  atan2 already
  // handles the q vs -q double-cover; we just wrap into the canonical range.
  let angle = 2 * Math.atan2(dot, quat.w)
  while (angle >  Math.PI) angle -= 2 * Math.PI
  while (angle < -Math.PI) angle += 2 * Math.PI

  const clamped = Math.max(minAngleRad, Math.min(maxAngleRad, angle))
  if (Math.abs(clamped - angle) < 1e-9) return quat.clone()

  const swingQ   = quat.clone().multiply(twistQ.clone().invert())
  const newTwist = new THREE.Quaternion().setFromAxisAngle(axisDir, clamped)
  return swingQ.multiply(newTwist)
}

/**
 * Convenience wrapper: clamp `quat`'s twist around the joint axis using the
 * joint's `min_angle_deg` / `max_angle_deg` mechanical limits.  Returns the
 * input unchanged when bounds are missing, malformed, or the default ±180°
 * window (which is equivalent to "unbounded" for a revolute joint).
 *
 * @param {THREE.Quaternion} quat
 * @param {object}           joint  ClusterJoint with axis_direction + bounds
 * @returns {THREE.Quaternion}
 */
export function clampQuatToJointBounds(quat, joint) {
  if (!joint) return quat.clone()
  const minDeg = joint.min_angle_deg
  const maxDeg = joint.max_angle_deg
  if (!Number.isFinite(minDeg) || !Number.isFinite(maxDeg)) return quat.clone()
  if (minDeg <= -179.999 && maxDeg >= 179.999) return quat.clone()
  const axisDir = new THREE.Vector3(...joint.axis_direction).normalize()
  return clampQuatTwist(quat, axisDir,
                        minDeg * Math.PI / 180,
                        maxDeg * Math.PI / 180)
}

/**
 * Compute a new Three.js Matrix4 for a child instance after a revolute rotation.
 *
 * Client-side equivalent of backend _apply_revolute_joint():
 *   R    = rotation about axisDir by angleRad
 *   t_new = axisOrigin + R * (t_base - axisOrigin)
 *   R_new = R * R_base
 *
 * @param {number[]}      baseValues  NADOC row-major float[16] — the base transform
 *                                    at joint current_value = 0 (base_transform.values
 *                                    or, if not set, the instance's current transform.values)
 * @param {number[]}      axisOrigin  [x, y, z] world-space pivot point
 * @param {number[]}      axisDir     [x, y, z] world-space rotation axis (need not be normalised)
 * @param {number}        angleRad    rotation angle in radians
 * @returns {THREE.Matrix4}           new world transform for the child instance
 */
export function computeRevoluteTransform(baseValues, axisOrigin, axisDir, angleRad) {
  // Load NADOC row-major → Three.js column-major
  const baseMat = new THREE.Matrix4().fromArray(baseValues).transpose()

  const axis = new THREE.Vector3(...axisDir).normalize()
  const rotMat = new THREE.Matrix4().makeRotationAxis(axis, angleRad)

  const origin  = new THREE.Vector3(...axisOrigin)
  const basePos = new THREE.Vector3().setFromMatrixPosition(baseMat)

  // t_new = origin + R * (base_pos - origin)
  const newPos = basePos.clone().sub(origin).applyMatrix4(rotMat).add(origin)

  // R_new = R * R_base  (extract upper-left 3×3 from baseMat)
  const baseRot = new THREE.Matrix4().extractRotation(baseMat)
  const newRot  = rotMat.clone().multiply(baseRot)

  // Assemble final matrix
  newRot.setPosition(newPos)
  return newRot
}
