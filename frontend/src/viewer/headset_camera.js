import { Matrix4, Quaternion, Vector3 } from 'three'
import { validateVRAvatar } from './vr_avatar_protocol.js'

/** Tracking metres -> shared source coordinates, including model manipulation. */
export function headsetCamera(value) {
  // Follow depends only on tracking, not optional controller/menu drawing data.
  // Tool menus can change independently while the same valid head pose continues.
  const pose = validateVRAvatar(value == null ? value : {
    schema: value.schema, trackingToSource: value.trackingToSource,
    head: value.head, hands: [null, null],
  })
  if (!pose) return null
  const transform = new Matrix4().fromArray(pose.trackingToSource)
  const orientation = new Quaternion().fromArray(pose.head.orientation)
  const position = new Vector3().fromArray(pose.head.position).applyMatrix4(transform)
  const forward = new Vector3(0, 0, -1).applyQuaternion(orientation).transformDirection(transform)
  const up = new Vector3(0, 1, 0).applyQuaternion(orientation).transformDirection(transform)
  const unitsPerMeter = new Vector3().setFromMatrixColumn(transform, 0).length()
  return { position: position.toArray(), target: position.clone().addScaledVector(forward, unitsPerMeter).toArray(), up: up.toArray(),
    fov: 70, near: .005 * unitsPerMeter, far: 1000 * unitsPerMeter, orbitMode: 'trackball', source: 'headset', unitsPerMeter }
}

/** Smooth a first-person camera without orbiting around its moving look target. */
export function smoothHeadsetCamera(previous, target, seconds) {
  const dt = Math.max(0, Math.min(.1, seconds)), alpha = 1 - Math.exp(-dt / .18)
  const position = new Vector3().fromArray(previous.position), next = new Vector3().fromArray(target.position)
  const distance = position.distanceTo(next)
  // Bound fast translations to one tracking metre/second and turns to 90°/second.
  position.lerp(next, Math.min(alpha, distance > 0 ? target.unitsPerMeter * dt / distance : 1))
  const rotation = camera => new Quaternion().setFromRotationMatrix(new Matrix4().lookAt(
    new Vector3().fromArray(camera.position), new Vector3().fromArray(camera.target), new Vector3().fromArray(camera.up)))
  const q = rotation(previous), end = rotation(target), angle = q.angleTo(end)
  q.slerp(end, Math.min(alpha, angle > 0 ? Math.PI / 2 * dt / angle : 1))
  return { ...target, position: position.toArray(), target: new Vector3(0, 0, -target.unitsPerMeter).applyQuaternion(q).add(position).toArray(),
    up: new Vector3(0, 1, 0).applyQuaternion(q).toArray() }
}
