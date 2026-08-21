import { describe, it, expect } from 'vitest'
import {
  honeycombCellWorldPos,
  isForwardCell,
  squareCellWorldPos,
} from './lattice_math.js'

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

describe('desktop lattice position measurements', () => {
  it('places odd honeycomb neighbours exactly 2.25 nm apart', () => {
    const origin = honeycombCellWorldPos(0, 0, 'XY', 0)
    const odd = honeycombCellWorldPos(0, 1, 'XY', 0)
    expect(odd.x - origin.x).toBeCloseTo(1.125 * Math.sqrt(3), 12)
    expect(odd.y - origin.y).toBeCloseTo(1.125, 12)
    expect(odd.distanceTo(origin)).toBeCloseTo(2.25, 12)
  })

  it('uses 3.375 nm honeycomb rows and 2.25 nm square pitches', () => {
    const hcA = honeycombCellWorldPos(-2, 3, 'XY', 0)
    const hcB = honeycombCellWorldPos(-1, -1, 'XY', 0)
    expect(hcB.x - hcA.x).toBeCloseTo(-4 * 1.125 * Math.sqrt(3), 12)
    expect(hcB.y - hcA.y).toBeCloseTo(2.25, 12)

    const sqA = squareCellWorldPos(1, 1, 'XY', 0)
    const sqB = squareCellWorldPos(3, -2, 'XY', 0)
    expect(sqB.x - sqA.x).toBeCloseTo(-6.75, 12)
    expect(sqB.y - sqA.y).toBeCloseTo(4.5, 12)
  })
})
