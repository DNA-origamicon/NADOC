import { describe, it, expect } from 'vitest'
import { createGeometryState, sphereMatrix, bondMatrix, writeSphereMatrix, writeBondMatrix } from './geometry_builder.js'

describe('allocation-free instance writes', () => {
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
