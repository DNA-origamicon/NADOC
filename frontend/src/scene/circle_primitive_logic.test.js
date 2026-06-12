import { describe, it, expect } from 'vitest'
import {
  columnLengths,
  circleFootprint,
  circularitySpread,
  impliedRadii,
  DEFAULT_MIN_CHORD_BP,
} from './circle_primitive_logic.js'

// Oracle shared with the Python core (backend/core/circle_primitive.py): at R=10.6 nm
// with pitch 2.25 nm / rise 0.334 nm / floor 16 bp, both sides must produce this exact
// length profile. Pinning the number here is what guarantees preview == server build.
const R = 10.6
const EXPECTED_AT_R = [34, 48, 56, 62, 62, 62, 56, 48, 34]

describe('columnLengths', () => {
  it('matches the shared Python oracle at R=10.6', () => {
    expect(columnLengths(R).map(([, bp]) => bp)).toEqual(EXPECTED_AT_R)
  })

  it('produces even, centre-symmetric lengths above the floor', () => {
    for (const radius of [6, 8, 10.6, 12, 15, 20]) {
      const lengths = columnLengths(radius).map(([, bp]) => bp)
      expect(lengths.length).toBeGreaterThan(0)
      expect(lengths.every((bp) => bp % 2 === 0)).toBe(true)
      expect(lengths.every((bp) => bp >= DEFAULT_MIN_CHORD_BP)).toBe(true)
      expect(lengths).toEqual([...lengths].reverse())
      expect(Math.max(...lengths)).toBe(lengths[(lengths.length - 1) / 2 | 0])
    }
  })

  it('honours a configurable floor', () => {
    expect(columnLengths(R, { minChordBp: 2 }).length)
      .toBeGreaterThan(columnLengths(R, { minChordBp: 40 }).length)
    expect(columnLengths(R, { minChordBp: 40 }).every(([, bp]) => bp >= 40)).toBe(true)
  })

  it('returns nothing for a radius below the floor', () => {
    expect(columnLengths(0.5)).toEqual([])
    expect(circleFootprint(0.5)).toBeNull()
  })
})

describe('circleFootprint', () => {
  it('is a single contiguous row anchored on the centre column', () => {
    const fp = circleFootprint(R)
    // Anchor = centre column (tangent point), the longest chord — not the first helix.
    expect(fp.anchorCell).toEqual([0, (fp.cells.length - 1) >> 1])
    expect(fp.cellLengths[fp.anchorCell[1]]).toBe(Math.max(...fp.cellLengths))
    expect(fp.cells.every(([row]) => row === 0)).toBe(true)
    expect(fp.cells.map(([, c]) => c)).toEqual([...Array(fp.cells.length).keys()])
    expect(fp.cellLengths).toEqual(EXPECTED_AT_R)
  })
})

describe('circularitySpread', () => {
  it('is far tighter than a hand-built disc', () => {
    const handBuilt = [16, 32, 54, 60, 64, 64, 60, 54, 32, 16] // small_circle.nadoc
    const baseline = circularitySpread(handBuilt)
    const generated = circularitySpread(columnLengths(R).map(([, bp]) => bp))
    expect(baseline).toBeGreaterThan(1.0)
    expect(generated).toBeLessThan(0.5)
    expect(generated).toBeLessThan(baseline / 2)
  })

  it('a perfect single-length disc has zero spread', () => {
    expect(impliedRadii([])).toEqual([])
    expect(circularitySpread([])).toBe(0)
  })
})
