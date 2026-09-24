import { LIVE_FRAME_LIMITS } from '../frontend/src/viewer/live_frame_capture.js'
import { liveTimeline } from '../frontend/src/viewer/live_timeline.js'
import { createHash } from 'node:crypto'
import { gunzipSync } from 'node:zlib'
import { decodeContainer } from '../frontend/src/viewer/package_container.js'
import { sceneChannels, decodeFrame } from '../frontend/src/viewer/trajectory_clip.js'

export function liveFrameLayout(scene) {
  const data = decodeContainer(scene.buffer.slice(scene.byteOffset, scene.byteOffset + scene.byteLength))
  return sceneChannels(data, LIVE_FRAME_LIMITS).values.length
}

/** One absolute frame per room; late joiners need only the base scene and this patch. */
export function acceptLiveFrame(room, body) {
  if (!Number.isSafeInteger(room.liveLayout)) throw new Error('Publish the job visualization before streaming frames')
  if (body.length <= 64 || body.subarray(0, 64).toString() !== room.revision) throw new Error('Frame belongs to a different visualization')
  let offset = 64, timeline = null
  if (body[64] !== 0x1f || body[65] !== 0x8b) {
    if (body.length < 68) throw new Error('Invalid live frame metadata')
    const length = body.readUInt32BE(64)
    if (length > 512 || length < 1 || 68 + length >= body.length) throw new Error('Invalid live frame metadata')
    timeline = liveTimeline(JSON.parse(body.subarray(68, 68 + length).toString('utf8')))
    offset = 68 + length
  }
  const bytes = body.subarray(offset)
  const raw = gunzipSync(bytes)
  decodeFrame(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength), room.liveLayout, LIVE_FRAME_LIMITS)
  const sequence = (room.liveSequence ?? 0) + 1
  const descriptor = { timeline, revision: room.revision, sequence, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') }
  room.liveSequence = sequence; room.liveFrame = { ...descriptor, buffer: bytes }
  room.presentation.setLiveFrame(descriptor)
  return descriptor
}
