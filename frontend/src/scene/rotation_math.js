/**
 * Pure rotation math extracted from main.js — Euler↔quaternion conversions for
 * the Move/Rotate transform fields (degrees, XYZ order) and swing-twist angle
 * extraction for revolute joints. THREE-only, no scene/DOM/store access, so these
 * are unit-testable directly (see rotation_math.test.js).
 */
import * as THREE from 'three'

// Quaternion [x,y,z,w] → Euler angles [rx,ry,rz] in degrees, XYZ order.
export function quatToEulerDeg(rotation) {
  const q = new THREE.Quaternion(rotation[0], rotation[1], rotation[2], rotation[3])
  const e = new THREE.Euler().setFromQuaternion(q, 'XYZ')
  const toDeg = r => r * (180 / Math.PI)
  return [toDeg(e.x), toDeg(e.y), toDeg(e.z)]
}

// Euler angles in degrees (XYZ order) → quaternion [x,y,z,w].
export function eulerDegToQuat(rx, ry, rz) {
  const toRad = d => d * (Math.PI / 180)
  const e = new THREE.Euler(toRad(rx), toRad(ry), toRad(rz), 'XYZ')
  const q = new THREE.Quaternion().setFromEuler(e)
  return [q.x, q.y, q.z, q.w]
}

/** Swing-twist decomposition: signed rotation angle (degrees) about joint.axis_direction. */
export function extractJointAngleDeg(quaternion, joint) {
  const axisDir = new THREE.Vector3(...joint.axis_direction).normalize()
  const dot = quaternion.x * axisDir.x + quaternion.y * axisDir.y + quaternion.z * axisDir.z
  const len = Math.sqrt(dot * dot + quaternion.w * quaternion.w)
  if (len < 1e-8) return 0
  return 2 * Math.atan2(dot / len, quaternion.w / len) * (180 / Math.PI)
}
