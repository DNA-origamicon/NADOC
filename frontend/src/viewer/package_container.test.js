import { describe, it, expect } from 'vitest'
import { encodeContainer, decodeContainer } from './package_container.js'

describe('prepared package container', () => {
  it('round-trips binary precision, subarrays and shared storage without numeric JSON expansion', () => {
    const array = new Float64Array([Math.PI, -1e-100, 42]).subarray(0, 2)
    const result = decodeContainer(encodeContainer({ name: 'protein / 金', array, shared: array, indices: new Uint16Array([0, 12]) }))
    expect(result.name).toBe('protein / 金')
    expect([...result.array]).toEqual([...array])
    expect(result.array.byteOffset).toBe(result.shared.byteOffset)
    expect(result.array.buffer).toBe(result.shared.buffer)
    expect(result.indices).toBeInstanceOf(Uint16Array)
  })
  it('rejects truncation, unsupported headers, malicious array bounds and prototype keys', () => {
    const data = encodeContainer({ positions: new Float32Array([1, 2, 3]) })
    expect(() => decodeContainer(data.slice(0, 18))).toThrow('header')
    expect(() => decodeContainer(data.slice(0, -1))).toThrow('bounds')
    new Uint8Array(data)[0] = 0
    expect(() => decodeContainer(data)).toThrow('Not a NADOC')
    expect(() => decodeContainer(encodeContainer({ a: { $array: 'Float32Array', offset: -8, length: 1 } }))).toThrow('bounds')
    expect(() => decodeContainer(encodeContainer(JSON.parse('{"__proto__":{"x":1}}')))).toThrow('key')
  })
})
