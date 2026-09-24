import { Vector3, Quaternion, Matrix4 } from 'three'

/** Smooth orbit and target interpolation; opposite views never cross the focal point. */
export function cameraBetween(start, end, t) {
  if (t >= 1) return end
  const v = a => new Vector3(...a), a = v(start.position), b = v(end.position), at = v(start.target), bt = v(end.target)
  const qa = new Quaternion().setFromRotationMatrix(new Matrix4().lookAt(a, at, v(start.up)))
  const qb = new Quaternion().setFromRotationMatrix(new Matrix4().lookAt(b, bt, v(end.up)))
  const q = qa.slerp(qb, t), target = at.clone().lerp(bt, t), radius = a.distanceTo(at) * (1 - t) + b.distanceTo(bt) * t
  return { ...end, position: new Vector3(0, 0, radius).applyQuaternion(q).add(target).toArray(), target: target.toArray(),
    up: new Vector3(0, 1, 0).applyQuaternion(q).toArray(), fov: start.fov + (end.fov - start.fov) * t }
}

export function createSharedViewMotion({ getView, requestFrame = requestAnimationFrame, cancelFrame = cancelAnimationFrame, now = () => performance.now() }) {
  let frame = null, cleanup = () => {}
  function cancel() { if (frame !== null) cancelFrame(frame); frame = null; cleanup(); cleanup = () => {} }
  return {
    cancel,
    move(pose) {
      cancel()
      const source = getView(), { camera, controls, canvas } = source
      const start = { position: camera.position.toArray(), target: controls.target.toArray(), up: camera.up.toArray(), fov: camera.fov }
      const enabled = controls.enabled, damping = controls.enableDamping, started = now()
      controls.enabled = false; controls.enableDamping = false; controls.update()
      const events = ['pointerdown', 'wheel', 'dblclick', 'keydown']
      for (const event of events) canvas?.addEventListener(event, cancel, true)
      cleanup = () => { controls.enabled = enabled; controls.enableDamping = damping; for (const event of events) canvas?.removeEventListener(event, cancel, true) }
      const step = time => {
        let current
        try { current = getView() } catch { cancel(); return }
        if (current.camera !== camera || current.controls !== controls || current.context !== source.context) { cancel(); return }
        const raw = Math.max(0, Math.min(1, (time - started) / 900)), t = raw * raw * (3 - 2 * raw)
        const value = cameraBetween(start, pose, t)
        camera.position.fromArray(value.position); controls.target.fromArray(value.target); camera.up.fromArray(value.up)
        camera.fov = value.fov; camera.near = value.near; camera.far = value.far; camera.updateProjectionMatrix(); controls.update()
        if (raw < 1) frame = requestFrame(step)
        else { source.finish?.(pose); cancel() }
      }
      frame = requestFrame(step)
    },
    dispose: cancel,
  }
}
