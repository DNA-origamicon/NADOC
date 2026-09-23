/** Small, bounded state channel for one immutable prepared snapshot. */
export function createPresentationState({ id, revision, now = Date.now }) {
  let sequence = 0, camera = null, presenting = false, windowStart = now(), updates = 0, closed = false
  const listeners = new Set()
  const presenters = new Set()
  let trajectory = null, liveFrame = null
  const snapshot = () => ({ schema: 1, room: id, revision, sequence, camera, presenting, trajectory, liveFrame, serverTime: now() })
  const send = response => { if (!response.write(`event: state\ndata: ${JSON.stringify(snapshot())}\n\n`)) response.destroy() }
  const broadcast = () => { for (const response of listeners) send(response) }
  const pause = () => { if (presenting && !closed) { presenting = false; sequence++; broadcast() } }
  function publish(value) {
    if (closed) throw new Error('This presentation has ended')
    if (value?.revision !== revision) throw new Error('Camera belongs to a different snapshot')
    const c = value.camera, vector = a => Array.isArray(a) && a.length === 3 && a.every(x => Number.isFinite(x) && Math.abs(x) <= 1e9)
    if (!c || !['position', 'target', 'up'].every(k => vector(c[k])) || Math.hypot(...c.up) < .001 ||
      Math.hypot(...c.position.map((v, i) => v - c.target[i])) < .000001 ||
      !Number.isFinite(c.fov) || c.fov < 1 || c.fov > 175 || !Number.isFinite(c.near) || c.near <= 0 ||
      !Number.isFinite(c.far) || c.far <= c.near || c.far > 1e12 || !['orbit', 'trackball', 'multiscale'].includes(c.orbitMode)) throw new Error('Invalid presenter camera')
    if (now() - windowStart >= 1000) { windowStart = now(); updates = 0 }
    if (updates >= 20) throw new Error('Too many camera updates')
    updates++
    camera = { position: [...c.position], target: [...c.target], up: [...c.up], fov: c.fov, near: c.near, far: c.far, orbitMode: c.orbitMode }
    sequence++; presenting = true; broadcast()
    return snapshot()
  }
  return { snapshot, publish, pause,
    setTrajectory(value) { trajectory = value; sequence++; broadcast(); return snapshot() },
    setLiveFrame(value) { liveFrame = value; sequence++; broadcast(); return snapshot() },
    replaceContent(next, clip) { revision = next; trajectory = clip; liveFrame = null; camera = null; presenting = false; sequence++; broadcast(); return snapshot() },
    replaceRevision(next) { revision = next; sequence++; broadcast() },
    leavePresenter() { pause(); for (const response of presenters) response.end() },
    subscribe(response, { presenter = false } = {}) {
      if (closed) { response.end(); return }
      if (listeners.size >= 8) { response.destroy(); return }
      listeners.add(response); if (presenter) presenters.add(response)
      response.on('close', () => { listeners.delete(response); if (presenters.delete(response) && presenters.size === 0) pause() }); send(response)
    },
    close() { closed = true; for (const response of listeners) response.end(); listeners.clear(); presenters.clear() },
  }
}
