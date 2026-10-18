/** Lossless NDGB v1 transport. Native coordinates remain binary64 throughout. */
export const NATIVE_GEOMETRY_MEDIA_TYPE = 'application/vnd.nadoc.geometry+binary'
// Bound expanded repeat/shape metadata as well as byte reads. Assembly copies
// share source arrays; they do not consume this per-response source budget.
const MAX_DECODED_ELEMENTS = 64 * 1024 * 1024

const TYPES = { f8: Float64Array, i4: Int32Array, u1: Uint8Array, u2: Uint16Array, u4: Uint32Array }
const littleEndian = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1
const readers = { f8: 'getFloat64', i4: 'getInt32', u1: 'getUint8', u2: 'getUint16', u4: 'getUint32' }
const integer = n => Number.isSafeInteger(n) && n >= 0
const invalid = detail => { throw new Error(`Invalid NDGB geometry: ${detail}`) }

/** Reconstruct ordinary arrays, including independent copies of repeated rows.
 * Placement validation and all existing JSON consumers see the same shape.
 */
export function decodeNativeGeometryBinary(buffer, { maxElements = MAX_DECODED_ELEMENTS } = {}) {
  if (!integer(maxElements)) invalid('decoded element budget')
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 16) invalid('incomplete prefix')
  const prefix = new DataView(buffer)
  if (prefix.getUint32(0, true) !== 0x4247444e || prefix.getUint32(4, true) !== 1) invalid('unsupported format')
  const headerBytes = prefix.getUint32(8, true), dataBytes = prefix.getUint32(12, true)
  const headerEnd = 16 + headerBytes, dataStart = Math.ceil(headerEnd / 8) * 8
  if (dataStart + dataBytes !== buffer.byteLength) invalid('buffer lengths')
  const header = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(new Uint8Array(buffer, 16, headerBytes)))
  if (header?.format !== 'ndgb1' || !Object.hasOwn(header, 'payload')) invalid('header')
  let allocated = 0
  const claim = count => {
    if (!integer(count) || count > maxElements - allocated) invalid('decoded element budget exceeded')
    allocated += count
  }
  const decodeObject = (value, depth) => {
    const entries = Object.entries(value)
    claim(entries.length)
    return Object.fromEntries(entries.map(([k, v]) => [k, decode(v, depth + 1)]))
  }
  const slots = value => value && typeof value === 'object'
    ? Object.values(value).reduce((n, item) => n + 1 + slots(item), 0) : 0
  const clone = value => Array.isArray(value) ? value.map(clone)
    : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, clone(v)])) : value
  function decode(value, depth = 0) {
    if (depth > 256) invalid('nesting depth')
    if (Array.isArray(value)) { claim(value.length); return value.map(item => decode(item, depth + 1)) }
    if (!value || typeof value !== 'object') return value
    if (!Object.hasOwn(value, '$nadoc')) return decodeObject(value, depth)
    if (value.$nadoc === 'literal') {
      if (!value.value || Array.isArray(value.value) || typeof value.value !== 'object') invalid('literal')
      return decodeObject(value.value, depth)
    }
    if (value.$nadoc === 'repeat') {
      if (!integer(value.count) || value.count > 0xffffffff) invalid('repeat count')
      const item = decode(value.value, depth + 1)
      claim(value.count * (1 + slots(item)))
      return item && typeof item === 'object'
        ? Array.from({ length: value.count }, () => clone(item)) : new Array(value.count).fill(item)
    }
    if (value.$nadoc !== 'array') invalid('unknown descriptor')
    const Type = TYPES[value.dtype], { shape, offset, nbytes } = value
    if (!Object.hasOwn(TYPES, value.dtype) || !Array.isArray(shape) || !shape.length || shape.length > 256
        || shape.some(n => !integer(n) || n > 0xffffffff)
        || !integer(offset) || offset % 8 || !integer(nbytes) || offset + nbytes > dataBytes) invalid('array descriptor')
    const count = shape.reduce((a, b) => a * b, 1)
    if (!integer(count) || count * Type.BYTES_PER_ELEMENT !== nbytes) invalid('array shape')
    let prefixCount = 1, requiredSlots = 0
    for (const length of shape) { prefixCount *= length; requiredSlots += prefixCount }
    claim(requiredSlots)
    const table = value.table, boolean = value.kind === 'bool'
    if (Object.hasOwn(value, 'kind') && !boolean) invalid('array kind')
    if (table !== undefined && (boolean || shape.length !== 1 || !value.dtype.startsWith('u')
        || !Array.isArray(table) || table.some(v => v !== null && typeof v !== 'string'))) invalid('dictionary')
    if (boolean && value.dtype !== 'u1') invalid('boolean dtype')
    const typed = littleEndian ? new Type(buffer, dataStart + offset, count) : null
    const view = typed ? null : new DataView(buffer, dataStart + offset, nbytes)
    let cursor = 0
    const next = () => {
      const n = typed ? typed[cursor++] : view[readers[value.dtype]](cursor++ * Type.BYTES_PER_ELEMENT, true)
      if (table !== undefined) {
        if (n >= table.length) invalid('dictionary index')
        return table[n]
      }
      if (boolean) {
        if (n !== 0 && n !== 1) invalid('boolean value')
        return n === 1
      }
      if (!Number.isFinite(n)) invalid('non-finite number')
      return n
    }
    const nest = dim => {
      const result = new Array(shape[dim])
      if (dim === shape.length - 1) for (let i = 0; i < result.length; i++) result[i] = next()
      else for (let i = 0; i < result.length; i++) result[i] = nest(dim + 1)
      return result
    }
    return nest(0)
  }
  return decode(header.payload)
}

/** JSON remains supported for old servers and structured HTTP errors. */
export async function readGeometryResponse(response) {
  const mediaType = response.headers?.get?.('Content-Type')?.split(';')[0]?.trim().toLowerCase()
  if (mediaType === NATIVE_GEOMETRY_MEDIA_TYPE) return decodeNativeGeometryBinary(await response.arrayBuffer())
  return response.json().catch(() => null)
}
