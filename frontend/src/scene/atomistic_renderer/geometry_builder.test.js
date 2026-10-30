import { describe, it, expect } from 'vitest'
import { createGeometryState, sphereMatrix, bondMatrix, writeSphereMatrix, writeBondMatrix } from './geometry_builder.js'

describe('allocation-free instance writes', () => {
  it('preserves compose arithmetic for varied directions, scales and destination precision', () => {
    let seed = 1234567
    const random = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32)
    const cases = [
      [0, 0, 0, 0, -1, 0, .04], [0, 0, 0, 1e-12, -1, 1e-12, 0],
      [-0, 0, -0, 1e-9, 0, 0, -.1], [0, 0, 0, 1e-10, 0, 0, 1],
    ]
    for (let i = 0; i < 1000; i++) {
      cases.push(Array.from({ length: 7 }, () => (random() - .5) * 100))
    }
    for (const Type of [Float32Array, Float64Array]) for (const args of cases) {
      const expected = new Type(48).fill(17), actual = new Type(expected)
      const reference = bondMatrix(createGeometryState(), ...args)
      if (reference) reference.toArray(expected, 16)
      expect(writeBondMatrix(createGeometryState(), actual, 16, ...args)).toBe(Boolean(reference))
      expect(actual).toEqual(expected)
    }
  })

  it('matches all matrix entries including both axial bond directions and tiny bonds', () => {
    const state = createGeometryState(), out = new Float32Array(48).fill(17)
    for (const [a, b] of [
      [[1, 2, 3], [1, 3, 3]], [[1, 2, 3], [1, 1, 3]],
      [[-3.12, .17, 8.5], [7.9, -12.31, .26]], [[0, 0, 0], [1e-8, 0, 0]],
    ]) {
      const expected = new Float32Array(16)
      bondMatrix(state, ...a, ...b, .04).toArray(expected)
      expect(writeBondMatrix(state, out, 16, ...a, ...b, .04)).toBe(true)
      expect(out.slice(16, 32)).toEqual(expected)
      expect(out[0]).toBe(17); expect(out[32]).toBe(17)
    }
    for (const scale of [0, .07, 1]) {
      const expected = new Float32Array(16)
      sphereMatrix(state, -1.7, 2.8, 13.1, scale).toArray(expected)
      writeSphereMatrix(out, 16, -1.7, 2.8, 13.1, scale)
      expect(out.slice(16, 32)).toEqual(expected)
    }
  })

  it('leaves the degenerate-bond hiding decision to its caller', () => {
    const out = new Float32Array(16).fill(17)
    expect(writeBondMatrix(createGeometryState(), out, 0, 1, 2, 3, 1, 2, 3, .04)).toBe(false)
    expect(out).toEqual(new Float32Array(16).fill(17))
  })
})
