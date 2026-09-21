/** Binary arrays stay binary: no base64 expansion or per-coordinate JSON objects. */
export const PACKAGE_LIMIT = 512 * 1024 * 1024
const HEADER = 16, META_LIMIT = 16 * 1024 * 1024
const MAGIC = 'NADOCVW1'
const TYPES = { Float32Array, Float64Array, Uint32Array, Uint16Array, Uint8Array, Int32Array, Int16Array, Int8Array, Uint8ClampedArray }

export function encodeContainer(manifest) {
  const arrays = [], offsets = new Map()
  let size = 0
  const json = JSON.stringify(manifest, (_key, value) => {
    if (!ArrayBuffer.isView(value)) return value
    if (!Object.hasOwn(TYPES, value.constructor.name)) throw new Error('Unsupported package array')
    if (!offsets.has(value)) {
      size = Math.ceil(size / 8) * 8
      offsets.set(value, { $array: value.constructor.name, offset: size, length: value.length })
      arrays.push({ value, offset: size }); size += value.byteLength
    }
    return offsets.get(value)
  })
  const metadata = new TextEncoder().encode(json)
  const start = Math.ceil((HEADER + metadata.length) / 8) * 8
  if (metadata.length > META_LIMIT || start + size > PACKAGE_LIMIT) throw new Error('Viewer package exceeds the current 512 MB limit')
  const buffer = new ArrayBuffer(start + size), bytes = new Uint8Array(buffer)
  bytes.set(new TextEncoder().encode(MAGIC))
  new DataView(buffer).setUint32(8, metadata.length, true)
  new DataView(buffer).setUint32(12, start, true)
  bytes.set(metadata, HEADER)
  for (const { value, offset } of arrays) bytes.set(new Uint8Array(value.buffer, value.byteOffset, value.byteLength), start + offset)
  return buffer
}

export function decodeContainer(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < HEADER || buffer.byteLength > PACKAGE_LIMIT) throw new Error('Invalid viewer package size')
  const bytes = new Uint8Array(buffer), view = new DataView(buffer)
  if (new TextDecoder().decode(bytes.subarray(0, 8)) !== MAGIC) throw new Error('Not a NADOC viewer package')
  const length = view.getUint32(8, true), start = view.getUint32(12, true)
  if (length > META_LIMIT || start !== Math.ceil((HEADER + length) / 8) * 8 || start > bytes.length) throw new Error('Invalid package header')
  return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(HEADER, HEADER + length)), (key, value) => {
    if (['__proto__', 'prototype', 'constructor'].includes(key)) throw new Error('Invalid package key')
    if (!value || typeof value !== 'object' || !Object.hasOwn(value, '$array')) return value
    const { $array: type, offset, length: count } = value
    if (!Object.hasOwn(TYPES, type)) throw new Error('Unsupported package array')
    const Type = TYPES[type]
    if (!Number.isSafeInteger(offset) || offset < 0 || offset % 8 || !Number.isSafeInteger(count) || count < 0 || count * Type.BYTES_PER_ELEMENT > bytes.length - start - offset) throw new Error('Invalid package array bounds')
    return new Type(buffer, start + offset, count)
  })
}
