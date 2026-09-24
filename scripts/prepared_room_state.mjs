import { validateSharedCamera } from './prepared_camera.mjs'
/** Small, bounded state channel for one immutable prepared snapshot. */
export function createPresentationState({ id, revision, now = Date.now }) {
  let sequence = 0, camera = null, presenting = false, windowStart = now(), updates = 0, closed = false
  const listeners = new Set()
  const presenters = new Set()
  let trajectory = null, liveFrame = null, loading = null, participants = []
  const snapshot = () => ({ schema: 1, room: id, revision, sequence, camera, presenting, trajectory, liveFrame, loading, participants, ended: closed, serverTime: now() })
  const send = response => { if (!response.write(`event: state\ndata: ${JSON.stringify(snapshot())}\n\n`)) response.destroy() }
  const broadcast = () => { for (const response of listeners) send(response) }
  const pause = () => { if (presenting && !closed) { presenting = false; sequence++; broadcast() } }
  function publish(value) {
    if (closed) throw new Error('This presentation has ended')
    if (value?.revision !== revision) throw new Error('Camera belongs to a different snapshot')
    const validated = validateSharedCamera(value.camera)
    if (now() - windowStart >= 1000) { windowStart = now(); updates = 0 }
    if (updates >= 20) throw new Error('Too many camera updates')
    updates++
    camera = validated
    sequence++; presenting = true; broadcast()
    return snapshot()
  }
  return { snapshot, publish, pause,
    setParticipants(value) { if (!closed && JSON.stringify(value) !== JSON.stringify(participants)) { participants = value; sequence++; broadcast() } },
    setLoading(value) {
      if (value !== null && (!value || typeof value !== 'object' || (value.fraction !== null && (!Number.isFinite(value.fraction) || value.fraction < 0 || value.fraction > 1)))) throw new Error('Invalid visualization progress')
      loading = value === null ? null : { fraction: value.fraction }; sequence++; broadcast(); return snapshot()
    },
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
    close() { if (closed) return; closed = true; presenting = false; loading = null; sequence++; broadcast(); for (const response of listeners) response.end(); listeners.clear(); presenters.clear() },
  }
}
