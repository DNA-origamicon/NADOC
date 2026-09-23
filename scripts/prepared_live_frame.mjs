import { createHash } from 'node:crypto'
import { gunzipSync } from 'node:zlib'
import { decodeContainer } from '../frontend/src/viewer/package_container.js'
import { sceneChannels, decodeFrame, FRAME_LIMIT } from '../frontend/src/viewer/trajectory_clip.js'

export function liveFrameLayout(scene) {
  const data = decodeContainer(scene.buffer.slice(scene.byteOffset, scene.byteOffset + scene.byteLength))
  return sceneChannels(data).values.length
}

/** One absolute frame per room; late joiners need only the base scene and this patch. */
export function acceptLiveFrame(room, body) {
  if (!Number.isSafeInteger(room.liveLayout)) throw new Error('Publish the job visualization before streaming frames')
  if (body.length <= 64 || body.length > FRAME_LIMIT + 64 || body.subarray(0, 64).toString() !== room.revision) throw new Error('Frame belongs to a different visualization')
  const bytes = body.subarray(64), raw = gunzipSync(bytes, { maxOutputLength: FRAME_LIMIT })
  decodeFrame(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength), room.liveLayout)
  const sequence = (room.liveSequence ?? 0) + 1
  const descriptor = { revision: room.revision, sequence, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') }
  room.liveSequence = sequence; room.liveFrame = { ...descriptor, buffer: bytes }
  room.presentation.setLiveFrame(descriptor)
  return descriptor
}
