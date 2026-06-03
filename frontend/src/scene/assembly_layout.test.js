import { describe, it, expect } from 'vitest'
import { assemblyDuplicateOffset } from './assembly_layout.js'

describe('assemblyDuplicateOffset', () => {
  it('uses x-extent + gap when it exceeds the floor', () => {
    expect(assemblyDuplicateOffset({ size: { x: 20 } })).toEqual([22, 0, 0]) // 20 + 2 gap
  })
  it('applies the 5 nm floor for small parts', () => {
    expect(assemblyDuplicateOffset({ size: { x: 1 } })).toEqual([5, 0, 0]) // max(5, 1+2)
  })
  it('falls back to radius*2 when size is absent', () => {
    expect(assemblyDuplicateOffset({ radius: 10 })).toEqual([22, 0, 0]) // 20 + 2
  })
  it('returns null for no entry', () => {
    expect(assemblyDuplicateOffset(null)).toBeNull()
    expect(assemblyDuplicateOffset(undefined)).toBeNull()
  })
})
