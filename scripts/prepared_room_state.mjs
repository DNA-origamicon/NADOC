import { encodeVRUIState } from '../frontend/src/viewer/vr_ui_stream.js'
import { validateVRAvatar } from '../frontend/src/viewer/vr_avatar_protocol.js'
import { validateSharedCamera } from './prepared_camera.mjs'
/** Small, bounded state channel for one immutable prepared snapshot. */
export function createPresentationState({ id, revision, now = Date.now }) {
  let sequence = 0, camera = null, presenting = false, windowStart = now(), updates = 0, closed = false
  const listeners = new Set()
  const presenters = new Set()
  let trajectory = null, liveFrame = null, loading = null, participants = [], drawings = []
  let manualViewLock = false, animationViewLock = false
  let avatar = null, avatarWindow = now(), avatarUpdates = 0
  const snapshot = () => ({ schema: 1, room: id, revision, sequence, camera, presenting, viewLocked: manualViewLock || animationViewLock, animationActive: animationViewLock, avatar, trajectory, liveFrame, loading, participants, drawings, ended: closed, serverTime: now() })
  const textureCaches = new WeakMap()
  const encode = (state, response) => {
    if (!textureCaches.has(response)) textureCaches.set(response, new Map())
    return `event: state\ndata: ${JSON.stringify(encodeVRUIState(state, textureCaches.get(response)))}\n\n`
  }
  // A complete menu packet can exceed Node's writable high-water mark even
  // on localhost. Backpressure means wait, not a failed connection. Keep only
  // the latest state while draining; a stalled guest cannot build a pose queue.
  const pending = new Map()
  const send = (response, message) => {
    if (pending.has(response)) { pending.get(response).message = message; return }
    if (response.write(encode(message, response))) return
    const wait = { message: null, timer: null }
    pending.set(response, wait)
    const drain = () => {
      if (pending.get(response) !== wait) return
      clearTimeout(wait.timer); pending.delete(response); response.removeListener('close', closed)
      if (wait.message) send(response, wait.message)
    }
    wait.timer = setTimeout(() => { pending.delete(response); response.destroy() }, 5000)
    wait.timer.unref?.()
    const closed = () => { clearTimeout(wait.timer); pending.delete(response); response.removeListener('drain', drain) }
    response.once('drain', drain)
    response.once('close', closed)
  }
  const broadcast = () => { if (!listeners.size) return; const message = snapshot(); for (const response of listeners) send(response, message) }
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
    setDrawings(value) { drawings = value; sequence++; broadcast() },
    setViewLock(value, animation = false) {
      if (typeof value !== 'boolean') throw new Error('Invalid perspective lock')
      if (animation) animationViewLock = value; else manualViewLock = value
      sequence++; broadcast(); return snapshot()
    },
    publishAvatar(value) {
      if (closed || value?.revision !== revision) throw Error('VR presenter belongs to a different snapshot')
      if (now()-avatarWindow >= 1000) {avatarWindow=now();avatarUpdates=0}
      if (avatarUpdates >= 20) throw Error('Too many VR presenter updates')
      const pose = validateVRAvatar(value.avatar)
      avatarUpdates++; avatar = pose ? { pose, expiresAt: now()+1500 } : null
      sequence++; broadcast(); return { ok:true }
    },
    expireAvatar() { if(avatar && now()>=avatar.expiresAt){avatar=null;sequence++;broadcast()} },
    setParticipants(value) { if (!closed && JSON.stringify(value) !== JSON.stringify(participants)) { participants = value; sequence++; broadcast() } },
    setLoading(value) {
      if (value !== null && (!value || typeof value !== 'object' || (value.fraction !== null && (!Number.isFinite(value.fraction) || value.fraction < 0 || value.fraction > 1)))) throw new Error('Invalid visualization progress')
      loading = value === null ? null : { fraction: value.fraction }; sequence++; broadcast(); return snapshot()
    },
    setTrajectory(value) { trajectory = value; sequence++; broadcast(); return snapshot() },
    setLiveFrame(value) { liveFrame = value; if (value?.animation) { camera = value.animation.camera; presenting = true }; sequence++; broadcast(); return snapshot() },
    replaceContent(next, clip) { avatar=null; revision = next; trajectory = clip; liveFrame = null; camera = null; presenting = false; sequence++; broadcast(); return snapshot() },
    replaceRevision(next) { avatar=null; revision = next; sequence++; broadcast() },
    leavePresenter() { pause(); for (const response of presenters) response.end() },
    subscribe(response, { presenter = false } = {}) {
      if (closed) { response.end(); return false }
      if (listeners.size >= 8) { response.destroy(); return false }
      listeners.add(response); if (presenter) presenters.add(response)
      response.on('close', () => { listeners.delete(response); if (presenters.delete(response) && presenters.size === 0) pause() }); send(response, snapshot())
      return listeners.has(response)
    },
    close() { if (closed) return; closed = true; avatar=null; presenting = false; loading = null; sequence++; broadcast(); for (const response of listeners) response.end(); listeners.clear(); presenters.clear() },
  }
}
