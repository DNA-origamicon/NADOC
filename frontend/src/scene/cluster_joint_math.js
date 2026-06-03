/**
 * Cluster ↔ joint transform math extracted from main.js. Pure: parameters +
 * THREE only (no scene/store). Unit-tested in cluster_joint_math.test.js.
 */
import * as THREE from 'three'

/**
 * New cluster {translation, rotation, pivot} after rotating it by `deltaRad`
 * about a joint's axis (pivot-corrected so the joint point stays fixed).
 * @param {{pivot?:number[],rotation?:number[],translation?:number[]}} cluster
 * @param {{axis_direction:number[],axis_origin:number[]}} joint
 * @param {number} deltaRad
 */
export function clusterTransformAfterJointDelta(cluster, joint, deltaRad) {
  const axisDir = new THREE.Vector3(...joint.axis_direction).normalize()
  const J = new THREE.Vector3(...joint.axis_origin)
  const P0 = new THREE.Vector3(...(cluster.pivot ?? [0, 0, 0]))
  const R0 = new THREE.Quaternion(...(cluster.rotation ?? [0, 0, 0, 1]))
  const T0 = new THREE.Vector3(...(cluster.translation ?? [0, 0, 0]))
  const R_delta = new THREE.Quaternion().setFromAxisAngle(axisDir, deltaRad)
  const R_new = R_delta.clone().multiply(R0)

  const inner = J.clone().sub(P0).applyQuaternion(R0).add(P0).add(T0).sub(J)
  const T_new = inner.clone().applyQuaternion(R_delta)
  const P0_minus_J = P0.clone().sub(J)
  const T_new_c = P0_minus_J.clone().applyQuaternion(R_new).sub(P0_minus_J).add(T_new)

  return {
    ...cluster,
    translation: [T_new_c.x, T_new_c.y, T_new_c.z],
    rotation: [R_new.x, R_new.y, R_new.z, R_new.w],
    pivot: [P0.x, P0.y, P0.z],
  }
}
