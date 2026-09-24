export const LIVE_FRAME_LIMITS = { maxBytes: Infinity, maxValues: Infinity }
import { sceneChannels, encodeFrame } from './trajectory_clip.js'
import { broadcastFingerprint } from './broadcast_fingerprint.js'

/** Snapshot identity excludes moving coordinates, but includes layout/material changes. */
export function liveSceneSignature(source) {
  return broadcastFingerprint(source, { coordinates: false })
}

/** Read the existing render buffers without exporting textures/geometry each frame. */
export function createLiveFrameCapture(data, source, limits = {}) {
  const base = sceneChannels(data, limits), signature = liveSceneSignature(source)
  const objects = new Map()
  source.scene.traverse(o => objects.set(o.uuid, o))
  const channels = base.channels.map(c => {
    const node = c.path.reduce((o, i) => o.children[i], data.root)
    const object = objects.get(node.uuid)
    if (!object) throw new Error('The visualization changed while preparing sharing. Retry when ready.')
    return { ...c, object }
  })
  return { signature, frame(next) {
    if (liveSceneSignature(next) !== signature) return null
    const values = new Float64Array(base.values.length)
    for (const c of channels) {
      const o = c.object
      if (c.kind === 'matrix') {
        if (o.matrixAutoUpdate) o.updateMatrix()
        values.set(o.matrix.elements, c.offset)
      } else {
        const a = c.kind === 'attribute' ? o.geometry.attributes[c.name] : o[c.kind]
        if (!a || a.count * a.itemSize !== c.array.length) return null
        if (a.isInterleavedBufferAttribute) {
          for (let i = 0; i < a.count; i++) for (let k = 0; k < a.itemSize; k++) values[c.offset + i * a.itemSize + k] = a.data.array[i * a.data.stride + a.offset + k]
        } else values.set(a.array, c.offset)
      }
    }
    return encodeFrame(base, { values, signature: base.signature }, limits)
  } }
}
