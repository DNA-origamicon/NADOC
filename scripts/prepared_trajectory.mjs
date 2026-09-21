import { createHash } from 'node:crypto'
import { gunzipSync } from 'node:zlib'
import { decodeContainer, encodeContainer } from '../frontend/src/viewer/package_container.js'
import { validateClip, sceneChannels, decodeFrame, CLIP_LIMIT, FRAME_LIMIT } from '../frontend/src/viewer/trajectory_clip.js'

const arrayBuffer = bytes => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)
export function unpackTrajectory(scene) {
  // Static packages remain opaque to the host; the browser validates their scene.
  let data
  try { data = decodeContainer(arrayBuffer(scene)) } catch { return { scene, trajectory: null } }
  if (!data.trajectory) return { scene, trajectory: null }
  const clip = validateClip(data.trajectory), total = sceneChannels(data).values.length
  let size = 0
  const frames = clip.frames.map(frame => {
    if (!(frame instanceof Uint8Array) || frame.byteLength > FRAME_LIMIT || (size += frame.byteLength) > CLIP_LIMIT) throw new Error('Trajectory exceeds the host clip budget')
    decodeFrame(arrayBuffer(gunzipSync(frame, { maxOutputLength: FRAME_LIMIT })), total)
    return Buffer.from(frame)
  })
  const descriptions = frames.map(frame => ({ bytes: frame.length, sha256: createHash('sha256').update(frame).digest('hex') }))
  const id = createHash('sha256').update(scene).digest('hex')
  data.trajectory = { ...clip, id, frames: descriptions }
  return { scene: Buffer.from(encodeContainer(data)), trajectory: { id, frames, bytes: size, fps: clip.fps, count: frames.length } }
}

export function updateTrajectory(room, value, now) {
  const clip = room.trajectory
  if (!clip || value?.id !== clip.id || !Number.isSafeInteger(value.frame) || value.frame < 0 || value.frame >= clip.count ||
      typeof value.playing !== 'boolean' || !Number.isFinite(value.fps) || value.fps < 1 || value.fps > 30) throw new Error('Invalid or obsolete trajectory command')
  return room.presentation.setTrajectory({ id: clip.id, frame: value.frame, playing: value.playing, fps: value.fps, at: now() })
}

export function initialTrajectory(clip, now) {
  return clip ? { id: clip.id, frame: 0, playing: false, fps: clip.fps, at: now() } : null
}
