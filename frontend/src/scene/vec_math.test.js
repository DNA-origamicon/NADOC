import { describe, it, expect } from 'vitest'
import { vecClose } from './vec_math.js'

describe('vecClose', () => {
  it('true for identical arrays', () => {
    expect(vecClose([1, 2, 3], [1, 2, 3])).toBe(true)
  })
  it('true within epsilon, false beyond it', () => {
    expect(vecClose([1, 2, 3], [1, 2, 3 + 1e-7])).toBe(true)
    expect(vecClose([1, 2, 3], [1, 2, 3.01])).toBe(false)
  })
  it('respects a custom epsilon', () => {
    expect(vecClose([0], [0.05], 0.1)).toBe(true)
    expect(vecClose([0], [0.2], 0.1)).toBe(false)
  })
  it('false for different lengths', () => {
    expect(vecClose([1, 2], [1, 2, 3])).toBe(false)
  })
  it('true for two empty arrays (defaults)', () => {
    expect(vecClose()).toBe(true)
    expect(vecClose([], [])).toBe(true)
  })
})
