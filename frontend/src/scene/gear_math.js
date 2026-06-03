/**
 * Revolute-joint / gear math extracted from main.js. Pure: parameters + THREE +
 * the pure makeRefVec helper only — no scene/store/assemblyRenderer. The live
 * appliers (_applyGearLive*, _applyFKLive) stay in main.js since they mutate the
 * renderer. Unit-tested in gear_math.test.js.
 */
import * as THREE from 'three'
import { makeRefVec } from './assembly_revolute_math.js'

/** Signed rotation angle (radians) implied by a world-space delta matrix about `axis`. */
export function signedAngleFromWorldDelta(delta, axis) {
  if (!delta || !axis) return 0
  const axisDir = axis.clone().normalize()
  const ref0 = makeRefVec(axisDir)
  const ref1 = ref0.clone().transformDirection(delta).normalize()
  const cross = new THREE.Vector3().crossVectors(ref0, ref1)
  return Math.atan2(cross.dot(axisDir), ref0.dot(ref1))
}

/** +1 / -1 sign for which side of a revolute joint is the moving one. */
export function movingSideSignForRevolute(joint, movingIds) {
  if (!joint || !movingIds) return 1
  const aMoving = joint.instance_a_id && movingIds.has(joint.instance_a_id)
  const bMoving = joint.instance_b_id && movingIds.has(joint.instance_b_id)
  if (bMoving && !aMoving) return 1
  if (aMoving && !bMoving) return -1
  return 1
}

/** Clamp a joint value to its [min_limit, max_limit] (either may be absent). */
export function clampJointValue(joint, value) {
  let next = value
  if (joint?.min_limit != null && next < joint.min_limit) next = joint.min_limit
  if (joint?.max_limit != null && next > joint.max_limit) next = joint.max_limit
  return next
}

/** Resolve the 'a'/'b' endpoint side for one end (`which`) of a gear relation. */
export function gearEndpointSide(rel, which, joint) {
  if (!joint) return 'b'
  const side = rel?.[`endpoint_${which}_side`]
  const instanceId = rel?.[`endpoint_${which}_instance_id`]
  if (side === 'a' || side === 'b') return side
  if (instanceId && instanceId === joint.instance_a_id) return 'a'
  return 'b'
}

/** 4×4 matrix rotating `angleRad` about an arbitrary axis through `axisOrigin`. */
export function rotationDeltaMatrix(axisOrigin, axisDir, angleRad) {
  const axis = new THREE.Vector3(...(axisDir ?? [0, 0, 1])).normalize()
  const origin = new THREE.Vector3(...(axisOrigin ?? [0, 0, 0]))
  return new THREE.Matrix4()
    .makeTranslation(origin.x, origin.y, origin.z)
    .multiply(new THREE.Matrix4().makeRotationAxis(axis, angleRad))
    .multiply(new THREE.Matrix4().makeTranslation(-origin.x, -origin.y, -origin.z))
}
