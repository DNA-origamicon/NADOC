import { Matrix4, Quaternion, Vector3 } from 'three'

/** Portable rendered-frame clips. Absolute patches never depend on a preceding frame. */
export const CLIP_LIMIT = 128 * 1024 * 1024
export const FRAME_LIMIT = 16 * 1024 * 1024
export const FRAME_COUNT_LIMIT = 120

export function sceneChannels(data, { maxValues = 8_000_000 } = {}) {
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
  if (length > maxValues) throw new Error('This scene is too large for the initial trajectory clip format')
  const values = new Float64Array(length)
  for (const channel of channels) values.set(channel.array, channel.offset)
  return { channels, values, signature: JSON.stringify([shapes, data.images, data.textures, data.render, data.view]) }
}

export function encodeFrame(base, next, { maxBytes = FRAME_LIMIT } = {}) {
  if (base.signature !== next.signature || base.values.length !== next.values.length) throw new Error('The scene structure changed during preparation. Keep a stable view without changing tools or representations.')
  const indices = []
  for (let i = 0; i < base.values.length; i++) if (base.values[i] !== next.values[i]) indices.push(i)
  const offset = Math.ceil((8 + indices.length * 4) / 8) * 8
  if (offset + indices.length * 8 > maxBytes) throw new Error(`A trajectory frame exceeds the ${maxBytes / 1048576} MiB limit. Use a smaller view or clip.`)
  const buffer = new ArrayBuffer(offset + indices.length * 8)
  new DataView(buffer).setUint32(0, indices.length, true)
  new Uint32Array(buffer, 8, indices.length).set(indices)
  new Float64Array(buffer, offset, indices.length).set(indices.map(i => next.values[i]))
  return buffer
}

export function decodeFrame(buffer, total, { maxBytes = FRAME_LIMIT } = {}) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 8 || buffer.byteLength > maxBytes) throw new Error('Invalid trajectory frame size')
  const count = new DataView(buffer).getUint32(0, true), offset = Math.ceil((8 + count * 4) / 8) * 8
  if (offset + count * 8 !== buffer.byteLength) throw new Error('Incomplete trajectory frame')
  const indices = new Uint32Array(buffer, 8, count), values = new Float64Array(buffer, offset, count)
  if (indices.some((v, i) => v >= total || (i && v <= indices[i - 1])) || !values.every(Number.isFinite)) throw new Error('Invalid trajectory coordinates')
  return { indices, values }
}

export async function gzipFrame(buffer, decompress = false, { maxBytes = FRAME_LIMIT } = {}) {
  const Stream = decompress ? globalThis.DecompressionStream : globalThis.CompressionStream
  if (!Stream) throw new Error('This browser needs gzip stream support for trajectory sharing')
  const reader = new Blob([buffer]).stream().pipeThrough(new Stream('gzip')).getReader()
  const chunks = []; let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read(); if (done) break
      size += value.byteLength
      if (size > maxBytes) throw new Error('Trajectory frame exceeds the decompression limit')
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
export function createClipApplier(current, limits = {}) {
  const layout = sceneChannels(current.data, limits), touched = new Set()
  const channels = layout.channels.map(c => {
    const object = c.path.reduce((o, i) => o.children[i], current.scene)
    const attribute = c.kind === 'attribute' ? object.geometry.attributes[c.name] : c.kind === 'matrix' ? null : object[c.kind]
    return { ...c, object, attribute, target: attribute?.array ?? object.matrix.elements }
  })
  let previous = null, blend = null
  function write(patch, restore) {
    let ci = 0
    for (let i = 0; i < patch.indices.length; i++) {
      const index = patch.indices[i]
      while (ci + 1 < channels.length && index >= channels[ci + 1].offset) ci++
      const c = channels[ci]; c.target[index - c.offset] = restore ? layout.values[index] : patch.values[i]; touched.add(c)
    }
  }
  function paint(patch) {
    if (previous) write(previous, true)
    write(patch, false); previous = patch
    for (const c of touched) {
      if (c.attribute) c.attribute.needsUpdate = true
      c.object.matrixWorldNeedsUpdate = true
      if (c.object.geometry) { c.object.geometry.boundingSphere = null; c.object.geometry.boundingBox = null }
      if (c.object.isInstancedMesh) { c.object.boundingSphere = null; c.object.boundingBox = null }
    }
    touched.clear(); current.scene.updateMatrixWorld(true)
  }
  return {
    apply(buffer) { blend = null; paint(decodeFrame(buffer, layout.values.length, limits)) },
    interpolate(from, to, fraction) {
      if (fraction <= 0) { this.apply(from); return }
      if (fraction >= 1) { this.apply(to); return }
      if (blend?.from !== from || blend?.to !== to) blend = prepareBlend(layout, from, to, limits)
      paint(blend.sample(fraction))
    },
    // Release endpoint buffers when playback stops or the cache is cleared.
    clearInterpolation() { blend = null },
  }
}

/** Only interpolate spatial channels. IDs, colors and visibility remain exact.
 * Work/storage scale with changed values, not the static geometry in the scene.
 * Matrices use decomposed transforms so rotating bonds do not collapse/shear.
 */
function prepareBlend(layout, from, to, limits) {
  const a = decodeFrame(from, layout.values.length, limits), b = decodeFrame(to, layout.values.length, limits)
  const indices = [], spatial = [], matrices = []
  let ai = 0, bi = 0, ci = 0
  while (ai < a.indices.length || bi < b.indices.length) {
    const index = Math.min(a.indices[ai] ?? Infinity, b.indices[bi] ?? Infinity)
    while (ci + 1 < layout.channels.length && index >= layout.channels[ci + 1].offset) ci++
    const channel = layout.channels[ci]
    if (channel.kind === 'matrix' || channel.kind === 'instanceMatrix') {
      const start = channel.offset + Math.floor((index - channel.offset) / 16) * 16
      let ae = ai, be = bi, translationOnly = true
      while (ae < a.indices.length && a.indices[ae] < start + 16) { const n = a.indices[ae++] - start; if (n < 12 || n > 14) translationOnly = false }
      while (be < b.indices.length && b.indices[be] < start + 16) { const n = b.indices[be++] - start; if (n < 12 || n > 14) translationOnly = false }
      // Most sphere/ion instances only translate: retain their tiny sparse patch
      // instead of allocating/decomposing a full transform per atom.
      if (translationOnly) {
        while (ai < ae || bi < be) {
          const n = Math.min(ai < ae ? a.indices[ai] : Infinity, bi < be ? b.indices[bi] : Infinity)
          indices.push(n); spatial.push(true)
          if (a.indices[ai] === n) ai++
          if (b.indices[bi] === n) bi++
        }
        continue
      }
      matrices.push(indices.length)
      for (let j = 0; j < 16; j++) { indices.push(start + j); spatial.push(false) }
      while (ai < a.indices.length && a.indices[ai] < start + 16) ai++
      while (bi < b.indices.length && b.indices[bi] < start + 16) bi++
    } else {
      indices.push(index)
      spatial.push(channel.kind === 'attribute' && ['position', 'instanceStart', 'instanceEnd'].includes(channel.name))
      if (a.indices[ai] === index) ai++
      if (b.indices[bi] === index) bi++
    }
  }
  const values = new Float64Array(indices.length), av = new Float64Array(indices.length), bv = new Float64Array(indices.length)
  ai = 0; bi = 0
  for (let i = 0; i < indices.length; i++) {
    const index = indices[i]
    av[i] = a.indices[ai] === index ? a.values[ai++] : layout.values[index]
    bv[i] = b.indices[bi] === index ? b.values[bi++] : layout.values[index]
  }
  const matrix = new Matrix4(), position = new Vector3(), rotation = new Quaternion(), scale = new Vector3()
  const transforms = matrices.map(offset => {
    const ap = new Vector3(), aq = new Quaternion(), as = new Vector3(), bp = new Vector3(), bq = new Quaternion(), bs = new Vector3()
    matrix.fromArray(av, offset).decompose(ap, aq, as)
    matrix.fromArray(bv, offset).decompose(bp, bq, bs)
    // Zero scale encodes hidden instances; never animate their appearance/location.
    const valid = [...as, ...bs].every(v => Number.isFinite(v) && Math.abs(v) > 1e-12) && [...aq, ...bq].every(Number.isFinite)
    return { offset, ap, aq, as, bp, bq, bs, valid }
  })
  const patch = { indices: new Uint32Array(indices), values }
  return { from, to, sample(t) {
    for (let i = 0; i < values.length; i++) values[i] = spatial[i] ? av[i] + (bv[i] - av[i]) * t : av[i]
    for (const m of transforms) if (m.valid) {
      position.lerpVectors(m.ap, m.bp, t); rotation.slerpQuaternions(m.aq, m.bq, t); scale.lerpVectors(m.as, m.bs, t)
      matrix.compose(position, rotation, scale).toArray(values, m.offset)
    }
    return patch
  } }
}
