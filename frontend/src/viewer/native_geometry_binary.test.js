import { describe, expect, it } from 'vitest'
import { decodeNativeGeometryBinary, readGeometryResponse, NATIVE_GEOMETRY_MEDIA_TYPE } from './native_geometry_binary.js'

function packet(payload, bytes = new Uint8Array()) {
  const header = new TextEncoder().encode(JSON.stringify({ format: 'ndgb1', payload }))
  const dataStart = Math.ceil((16 + header.length) / 8) * 8
  const result = new ArrayBuffer(dataStart + bytes.byteLength), prefix = new DataView(result)
  prefix.setUint32(0, 0x4247444e, true); prefix.setUint32(4, 1, true)
  prefix.setUint32(8, header.length, true); prefix.setUint32(12, bytes.byteLength, true)
  new Uint8Array(result, 16, header.length).set(header)
  new Uint8Array(result, dataStart).set(bytes)
  return result
}
const array = (dtype, shape, nbytes, extra = {}) => ({ $nadoc: 'array', dtype, shape, offset: 0, nbytes, ...extra })
const bytes = typed => new Uint8Array(typed.buffer)

describe('lossless native geometry binary transport', () => {
  it('preserves binary64 coordinates, signed zero, row order, and ordinary arrays', () => {
    const expected = [[1.2345678901234567, -0, 3], [4, -1e-120, 6]]
    const decoded = decodeNativeGeometryBinary(packet({ positions: array('f8', [2, 3], 48) }, bytes(new Float64Array(expected.flat()))))
    expect(decoded.positions).toEqual(expected)
    expect(Object.is(decoded.positions[0][1], -0)).toBe(true)
    expect(Array.isArray(decoded.positions[0])).toBe(true)
  })
  it('decodes dictionary metadata, nulls, booleans, and all integer widths', () => {
    expect(decodeNativeGeometryBinary(packet(array('u1', [4], 4, { table: ['helix', null, 'strand'] }), new Uint8Array([0, 2, 0, 1])))).toEqual(['helix', 'strand', 'helix', null])
    expect(decodeNativeGeometryBinary(packet(array('u1', [3], 3, { kind: 'bool' }), new Uint8Array([0, 1, 1])))).toEqual([false, true, true])
    for (const [dtype, Type, numbers] of [['i4', Int32Array, [-3, 3]], ['u2', Uint16Array, [256, 65535]], ['u4', Uint32Array, [65536, 4294967295]]]) {
      const data = new Type(numbers)
      expect(decodeNativeGeometryBinary(packet(array(dtype, [2], data.byteLength), bytes(data)))).toEqual(numbers)
    }
  })
  it('repeats constant values without aliasing mutable rows and preserves escaped metadata', () => {
    const payload = { rows: { $nadoc: 'repeat', count: 3, value: [1, 2, 3] },
      metadata: { $nadoc: 'literal', value: { $nadoc: 'user value', nested: { $nadoc: 'repeat', count: 2, value: null } } } }
    const decoded = decodeNativeGeometryBinary(packet(payload))
    expect(decoded.rows).toEqual([[1, 2, 3], [1, 2, 3], [1, 2, 3]])
    decoded.rows[0][0] = 9
    expect(decoded.rows[1][0]).toBe(1)
    expect(decoded.metadata).toEqual({ $nadoc: 'user value', nested: [null, null] })
  })
  it('preserves object keys without changing prototypes', () => {
    const result = decodeNativeGeometryBinary(packet(JSON.parse('{"__proto__":{"polluted":true},"constructor":"name"}')))
    expect(Object.getPrototypeOf(result)).toBe(Object.prototype)
    expect(Object.hasOwn(result, '__proto__')).toBe(true)
    expect({}.polluted).toBeUndefined()
  })
  it.each([
    [array('f8', [2], 8), new Uint8Array(8)],
    [array('f8', [1], 8, { offset: 1 }), new Uint8Array(16)],
    [array('f8', [-1], 8), new Uint8Array(8)],
    [array('constructor', [1], 8), new Uint8Array(8)],
    [array('u1', [1], 1, { table: ['x'] }), new Uint8Array([1])],
    [array('u1', [1], 1, { kind: 'bool' }), new Uint8Array([2])],
    [array('f8', [1], 8), bytes(new Float64Array([Infinity]))],
    [{ $nadoc: 'repeat', count: -1, value: null }, new Uint8Array()],
    [{ $nadoc: 'unknown' }, new Uint8Array()],
  ])('rejects malformed descriptors instead of returning partial geometry (%j)', (descriptor, data) => {
    expect(() => decodeNativeGeometryBinary(packet(descriptor, data))).toThrow('Invalid NDGB')
  })
  it('rejects truncated bodies and unsupported versions', () => {
    const data = packet({})
    expect(() => decodeNativeGeometryBinary(data.slice(0, -1))).toThrow('Invalid NDGB')
    new DataView(data).setUint32(4, 2, true)
    expect(() => decodeNativeGeometryBinary(data)).toThrow('unsupported format')
  })
  it('bounds cumulative expanded allocations before constructing arrays', () => {
    expect(() => decodeNativeGeometryBinary(packet(array('u1', [4294967295, 0], 0)))).toThrow('element budget')
    expect(() => decodeNativeGeometryBinary(packet({ $nadoc: 'repeat', count: 4294967295, value: null }))).toThrow('element budget')
    const repeated = { $nadoc: 'repeat', count: 3, value: [1, 2, 3] }
    expect(() => decodeNativeGeometryBinary(packet([repeated, repeated]), { maxElements: 25 })).toThrow('element budget')
    expect(decodeNativeGeometryBinary(packet(repeated), { maxElements: 15 })).toEqual([[1, 2, 3], [1, 2, 3], [1, 2, 3]])
  })
  it('selects binary by media type and keeps legacy JSON/errors compatible', async () => {
    const value = { errors: [], instances: {} }
    expect(await readGeometryResponse(new Response(packet(value), { headers: { 'Content-Type': NATIVE_GEOMETRY_MEDIA_TYPE } }))).toEqual(value)
    expect(await readGeometryResponse(new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } }))).toEqual(value)
    expect(await readGeometryResponse(new Response('bad gateway'))).toBeNull()
    await expect(readGeometryResponse(new Response(new ArrayBuffer(0), { headers: { 'Content-Type': NATIVE_GEOMETRY_MEDIA_TYPE } }))).rejects.toThrow('incomplete prefix')
  })
})
