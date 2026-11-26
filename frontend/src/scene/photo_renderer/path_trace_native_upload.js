// Binary fields retain the native worker's base64 JSON wire format, but neither
// an individual buffer nor the whole scene is ever assembled as one JS string.
const BINARY_CHUNK = 49152 // multiple of three: padding only in the final chunk
const ENCODING_BATCH = 1048576
export const NATIVE_UPLOAD_CHUNK = 8 * ENCODING_BATCH

function* fragments(value, ancestors = new Set(), measure = false) {
  if (ArrayBuffer.isView(value)) {
    if (measure) { yield 2 + 4 * Math.ceil(value.byteLength / 3); return }
    const bytes = new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
    yield '"'
    for (let offset = 0; offset < bytes.length; offset += BINARY_CHUNK)
      yield btoa(String.fromCharCode(...bytes.subarray(offset, offset + BINARY_CHUNK)))
    yield '"'
  } else if (value && typeof value === 'object') {
    if (ancestors.has(value)) throw new TypeError('Circular native scene payload')
    ancestors.add(value)
    const array = Array.isArray(value)
    yield array ? '[' : '{'
    let first = true
    for (const [key, child] of array ? value.entries() : Object.entries(value)) {
      const omitted = child === undefined || typeof child === 'function' || typeof child === 'symbol'
      if (!array && omitted) continue
      if (!first) yield ','
      first = false
      if (!array) { yield JSON.stringify(key); yield ':' }
      yield* fragments(omitted ? null : child, ancestors, measure)
    }
    yield array ? ']' : '}'
    ancestors.delete(value)
  } else {
    yield JSON.stringify(value)
  }
}

/** Exact encoded size without allocating base64 or a whole-scene string. */
export function nativeJSONSize(data, maxBytes = Infinity) {
  const utf8 = new TextEncoder()
  let size = 0
  for (const fragment of fragments(data, new Set(), true))
    size += typeof fragment === 'number' ? fragment : utf8.encode(fragment).byteLength
  if (size > maxBytes)
    throw new Error(`OptiX scene upload is ${(size / 1048576).toFixed(1)} MiB; currently available RAM/scratch capacity is ${(maxBytes / 1048576).toFixed(1)} MiB. Free resources or use WebGL/WebGPU export.`)
  return size
}

/** Yield bounded upload bodies; the caller awaits each transfer before asking
 * for more. Raw byte bodies bypass browser Blob storage quotas entirely. */
export async function* nativeJSONChunks(data, {signal} = {}) {
  const utf8 = new TextEncoder()
  let buffers = [], parts = [], characters = 0, size = 0
  const flush = () => {
    const bytes = utf8.encode(parts.join(''))
    size += bytes.byteLength
    buffers.push(bytes)
    parts = []; characters = 0
  }
  const join = () => {
    const result = new Uint8Array(size)
    let offset = 0
    for (const bytes of buffers) { result.set(bytes, offset); offset += bytes.byteLength }
    buffers = []; size = 0
    return result
  }
  signal?.throwIfAborted()
  for (const fragment of fragments(data)) {
    signal?.throwIfAborted()
    parts.push(fragment); characters += fragment.length
    if (characters >= ENCODING_BATCH || parts.length >= 4096) {
      flush()
      if (size >= NATIVE_UPLOAD_CHUNK) {
        yield join()
      }
      await new Promise(resolve => setTimeout(resolve, 0))
    }
  }
  signal?.throwIfAborted()
  if (parts.length) flush()
  if (buffers.length) yield join()
}

/** Small control/camera requests use the same wire format in a single body. */
export async function nativeJSONBlob(data, {signal, maxBytes = Infinity} = {}) {
  nativeJSONSize(data, maxBytes)
  const blobs = []
  for await (const blob of nativeJSONChunks(data, {signal})) blobs.push(blob)
  return new Blob(blobs, {type: 'application/json'})
}
