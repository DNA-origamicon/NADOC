/** Portable rendered-frame clips. Absolute patches never depend on a preceding frame. */
export const CLIP_LIMIT = 128 * 1024 * 1024
export const FRAME_LIMIT = 16 * 1024 * 1024
export const FRAME_COUNT_LIMIT = 120

export function sceneChannels(data) {
  const channels = [], shapes = [], seen = new Map(), geometry = new Map(data.geometries.map(g => [g.uuid, g]))
  const materials = new Map(data.materials.map(m => [m.uuid, m]))
  const clean = value => JSON.stringify(value, (k, v) => k === 'uuid' ? undefined : v)
  const add = (path, kind, name, array) => {
    channels.push({ path, kind, name, array, offset: 0 })
    shapes.push([kind, name, array.constructor.name, array.length])
  }
  function visit(node, path) {
    shapes.push([node.type, node.wideLine, node.name, node.count, node.layers, node.renderOrder, node.children.length,
      (Array.isArray(node.material) ? node.material : node.material ? [node.material] : []).map(id => clean(materials.get(id)))])
    add(path, 'matrix', '', node.matrix)
    for (const name of ['instanceMatrix', 'instanceColor']) if (node[name]) add(path, name, '', node[name].array)
    if (node.geometry) {
      if (seen.has(node.geometry)) shapes.push(['shared', seen.get(node.geometry)])
      else {
        seen.set(node.geometry, seen.size)
        const g = geometry.get(node.geometry)
        shapes.push([g.wideLine, g.instanceCount, g.groups, g.drawRange, g.index ? Array.from(g.index.array) : null])
        for (const name of Object.keys(g.attributes).sort()) {
          const a = g.attributes[name]
          shapes.push([a.itemSize, a.normalized, a.instanced, a.meshPerAttribute])
          add(path, 'attribute', name, a.array)
        }
      }
    }
    node.children.forEach((child, index) => visit(child, [...path, index]))
  }
  visit(data.root, [])
  let length = 0
  for (const channel of channels) { channel.offset = length; length += channel.array.length }
  if (length > 8_000_000) throw new Error('This scene is too large for the initial trajectory clip format')
  const values = new Float64Array(length)
  for (const channel of channels) values.set(channel.array, channel.offset)
  return { channels, values, signature: JSON.stringify([shapes, data.images, data.textures, data.render, data.view]) }
}

export function encodeFrame(base, next) {
  if (base.signature !== next.signature || base.values.length !== next.values.length) throw new Error('The scene structure changed during preparation. Use a stable Full view without changing tools or representations.')
  const indices = []
  for (let i = 0; i < base.values.length; i++) if (base.values[i] !== next.values[i]) indices.push(i)
  const offset = Math.ceil((8 + indices.length * 4) / 8) * 8
  if (offset + indices.length * 8 > FRAME_LIMIT) throw new Error('A trajectory frame exceeds the 16 MiB limit. Use a smaller view or clip.')
  const buffer = new ArrayBuffer(offset + indices.length * 8)
  new DataView(buffer).setUint32(0, indices.length, true)
  new Uint32Array(buffer, 8, indices.length).set(indices)
  new Float64Array(buffer, offset, indices.length).set(indices.map(i => next.values[i]))
  return buffer
}

export function decodeFrame(buffer, total) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 8 || buffer.byteLength > FRAME_LIMIT) throw new Error('Invalid trajectory frame size')
  const count = new DataView(buffer).getUint32(0, true), offset = Math.ceil((8 + count * 4) / 8) * 8
  if (offset + count * 8 !== buffer.byteLength) throw new Error('Incomplete trajectory frame')
  const indices = new Uint32Array(buffer, 8, count), values = new Float64Array(buffer, offset, count)
  if (indices.some((v, i) => v >= total || (i && v <= indices[i - 1])) || !values.every(Number.isFinite)) throw new Error('Invalid trajectory coordinates')
  return { indices, values }
}

export async function gzipFrame(buffer, decompress = false) {
  const Stream = decompress ? globalThis.DecompressionStream : globalThis.CompressionStream
  if (!Stream) throw new Error('This browser needs gzip stream support for trajectory sharing')
  const reader = new Blob([buffer]).stream().pipeThrough(new Stream('gzip')).getReader()
  const chunks = []; let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read(); if (done) break
      size += value.byteLength
      if (size > FRAME_LIMIT) throw new Error('Trajectory frame exceeds the decompression limit')
      chunks.push(value)
    }
  } finally { await reader.cancel().catch(() => {}) }
  return new Blob(chunks).arrayBuffer()
}

export function clipFrameAt(state, now, count) {
  return Math.max(0, Math.min(count - 1, Math.floor(state.frame + (state.playing ? Math.max(0, now - state.at) * state.fps / 1000 : 0))))
}

export function validateClip(clip) {
  if (clip?.version !== 1 || clip.encoding !== 'absolute-render-patch-gzip' || !Array.isArray(clip.frames) || clip.frames.length < 2 || clip.frames.length > FRAME_COUNT_LIMIT ||
    !Number.isFinite(clip.fps) || clip.fps < 1 || clip.fps > 30 || !Array.isArray(clip.sourceFrames) || clip.sourceFrames.length !== clip.frames.length ||
    clip.sourceFrames.some((n, i) => !Number.isSafeInteger(n) || n < 0 || (i && n <= clip.sourceFrames[i - 1]))) throw new Error('Invalid trajectory clip')
  return clip
}

/** Apply exact exported coordinates in place; no editor or scientific model dependency. */
export function createClipApplier(current) {
  const layout = sceneChannels(current.data), touched = new Set()
  const channels = layout.channels.map(c => {
    const object = c.path.reduce((o, i) => o.children[i], current.scene)
    const attribute = c.kind === 'attribute' ? object.geometry.attributes[c.name] : c.kind === 'matrix' ? null : object[c.kind]
    return { ...c, object, attribute, target: attribute?.array ?? object.matrix.elements }
  })
  let previous = null
  function write(patch, restore) {
    let ci = 0
    for (let i = 0; i < patch.indices.length; i++) {
      const index = patch.indices[i]
      while (ci + 1 < channels.length && index >= channels[ci + 1].offset) ci++
      const c = channels[ci]; c.target[index - c.offset] = restore ? layout.values[index] : patch.values[i]; touched.add(c)
    }
  }
  return { apply(buffer) {
    const patch = decodeFrame(buffer, layout.values.length)
    if (previous) write(previous, true)
    write(patch, false); previous = patch
    for (const c of touched) {
      if (c.attribute) c.attribute.needsUpdate = true
      c.object.matrixWorldNeedsUpdate = true
      if (c.object.geometry) { c.object.geometry.boundingSphere = null; c.object.geometry.boundingBox = null }
      if (c.object.isInstancedMesh) { c.object.boundingSphere = null; c.object.boundingBox = null }
    }
    touched.clear(); current.scene.updateMatrixWorld(true)
  } }
}
