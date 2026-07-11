import { describe, it, expect } from 'vitest'
import { isForwardCell } from './lattice_math.js'

describe('isForwardCell — caDNAno2 parity rule', () => {
  it('even (row+col) parity is FORWARD', () => {
    expect(isForwardCell(0, 0)).toBe(true)
    expect(isForwardCell(1, 1)).toBe(true)
    expect(isForwardCell(2, 4)).toBe(true)
    expect(isForwardCell(3, 5)).toBe(true)
  })

  it('odd (row+col) parity is REVERSE', () => {
    expect(isForwardCell(0, 1)).toBe(false)
    expect(isForwardCell(1, 0)).toBe(false)
    expect(isForwardCell(2, 5)).toBe(false)
  })

  it('handles negative coordinates (grid can extend below origin)', () => {
    expect(isForwardCell(-1, -1)).toBe(true)
    expect(isForwardCell(-1, 0)).toBe(false)
    expect(isForwardCell(-2, -4)).toBe(true)
    expect(isForwardCell(-3, 0)).toBe(false)
  })
})
