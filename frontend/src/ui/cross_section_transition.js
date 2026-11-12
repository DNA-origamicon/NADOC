import * as THREE from 'three'

/** Orbit around the moving target; quaternion interpolation avoids opposite-up singularities. */
export function createCrossSectionTransition({ requestFrame = requestAnimationFrame, cancelFrame = cancelAnimationFrame, now = () => performance.now(), onActive = () => {} } = {}) {
  let frame = null
  function cancel() {
    if (frame !== null) cancelFrame(frame)
    frame = null; onActive(false)
  }
  function move(camera, controls, pose, zoom = camera.zoom) {
    cancel()
    const start = { target: controls.target.clone(), rotation: camera.quaternion.clone(), distance: camera.position.distanceTo(controls.target), zoom: camera.zoom }
    const destination = camera.clone()
    destination.position.copy(pose.position); destination.up.copy(pose.up); destination.lookAt(pose.target)
    const rotation = new THREE.Quaternion(), direction = new THREE.Vector3(), up = new THREE.Vector3()
    const began = now()
    onActive(true)
    function tick(time) {
      const raw = Math.min(1, Math.max(0, (time - began) / 500))
      const t = raw * raw * (3 - 2 * raw)
      rotation.slerpQuaternions(start.rotation, destination.quaternion, t)
      controls.target.lerpVectors(start.target, pose.target, t)
      direction.set(0, 0, 1).applyQuaternion(rotation)
      up.set(0, 1, 0).applyQuaternion(rotation)
      camera.position.copy(controls.target).addScaledVector(direction, THREE.MathUtils.lerp(start.distance, pose.distance, t))
      camera.up.copy(raw === 1 ? pose.up : up)
      camera.zoom = THREE.MathUtils.lerp(start.zoom, zoom, t); camera.updateProjectionMatrix()
      controls.update(); camera.lookAt(controls.target); camera.updateMatrixWorld()
      if (raw < 1) frame = requestFrame(tick)
      else { frame = null; onActive(false) }
    }
    frame = requestFrame(tick)
  }
  return { move, cancel }
}
