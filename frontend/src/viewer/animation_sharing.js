import { decodeContainer } from './package_container.js'
import { createLiveFrameCapture, liveSceneSignature, LIVE_FRAME_LIMITS } from './live_frame_capture.js'
import { gzipFrame } from './trajectory_clip.js'
import { requireSharingCapabilities } from './sharing_capabilities.js'
import { animationFrame } from './animation_frame.js'

/** Playback awaits publication, so preparation/upload cannot skip the animation clock. */
export function initAnimationSharing({ prepared, getRoom, beforeStart, afterStop, onActive, onError,
  fetch: request = fetch, setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  let session = null, queue = Promise.resolve(), disposed = false, epoch = 0
  const enqueue = task => { const next = queue.catch(() => {}).then(task); queue = next; return next }
  async function send(s, action, body) {
    const response = await request(`/__nadoc_share/shares/${s.id}/broadcast/${action}`, { method: 'POST',
      headers: { 'X-NADOC-Share': '1', 'X-NADOC-Broadcast': s.lease ?? '' }, body })
    const value = await response.json()
    if (!response.ok) throw new Error(value.error || 'Animation sharing interrupted')
    return value
  }
  async function finish(restore = false) {
    const s = session; session = null
    try { if (s?.lease) await send(s, 'pause') }
    finally { onActive(false); if (s && !disposed) await afterStop(restore) }
  }
  async function publish(state, ticket) {
    const current = () => !disposed && ticket === epoch && state.isCurrent?.() !== false
    if (!current() || !getRoom() || (state.seek && !session)) return
    if (!session) {
      const room = getRoom()
      if (!room.capabilities?.includes('animation-stream-v1')) throw new Error('Restart presentation hosting to share animations.')
      onActive(true)
      await beforeStart()
      if (!current() || getRoom()?.id !== room.id) { onActive(false); return }
      const s = { id: room.id, capabilities: room.capabilities, lastTime: -Infinity }
      session = s
      Object.assign(s, await send(s, 'start', JSON.stringify({ jobStream: true, animation: true })))
    }
    const s = session
    if (s.id !== getRoom()?.id) { await finish(); return }
    // Always send both endpoints, seeks and loop turnarounds; otherwise sample at 15 Hz.
    if (!state.seek && state.time > s.lastTime && state.time - s.lastTime < 1 / 15 && state.time < state.duration) return
    let source = prepared.captureView(false)
    let raw = s.capture?.frame(source)
    if (!raw || liveSceneSignature(source) !== s.capture.signature) {
      const result = await prepared.exportView({ presentation: false })
      if (!result) throw new Error('Wait for the current view export before playing a shared animation.')
      requireSharingCapabilities(result, s.capabilities)
      if (!current()) return
      source = prepared.captureView(false)
      s.capture = createLiveFrameCapture(decodeContainer(result.buffer), source, LIVE_FRAME_LIMITS)
      raw = s.capture.frame(source)
      s.revision = (await send(s, 'scene', result.buffer)).revision
    }
    if (!current()) return
    if (!raw) throw new Error('Animation view changed while preparing its frame.')
    const animation = animationFrame({ ...state, camera: { ...source.pose, near: source.camera.near, far: source.camera.far } })
    const metadata = new TextEncoder().encode(JSON.stringify({ animation }))
    const compressed = await gzipFrame(raw, false, LIVE_FRAME_LIMITS)
    if (!current()) return
    const packet = new Uint8Array(68 + metadata.length + compressed.byteLength)
    packet.set(new TextEncoder().encode(s.revision))
    new DataView(packet.buffer).setUint32(64, metadata.length)
    packet.set(metadata, 68); packet.set(new Uint8Array(compressed), 68 + metadata.length)
    await send(s, 'frame', packet)
    s.lastTime = state.time
  }
  let heartbeat = false
  const timer = repeat(async () => {
    if (!session?.lease || heartbeat) return
    heartbeat = true
    try { await send(session, 'heartbeat') } catch (error) { onError(error.message) }
    finally { heartbeat = false }
  }, 4000)
  const stop = (restore = false) => { epoch++; return enqueue(() => finish(restore)) }
  return {
    frame(state) { const ticket = epoch; return enqueue(() => publish(state, ticket)).catch(async error => { await stop().catch(() => {}); onError(error.message); throw error }) },
    event(event) { if (['stopped', 'finished', 'baking_cancelled', 'baking_error'].includes(event.type)) void stop(event.type === 'stopped').catch(error => onError(error.message)) },
    stop,
    dispose() { disposed = true; cancel(timer); void stop().catch(() => {}) },
  }
}
