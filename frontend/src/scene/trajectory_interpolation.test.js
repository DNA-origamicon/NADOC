import { describe, it, expect } from 'vitest'
import { lerpCoordinates, cubicCoordinates, periodicPositionInterpolator, interpolationNeighbors } from './trajectory_interpolation.js'

const box = (size = 10, rotate = false) => Float32Array.from(
  Array.from({ length: 8 }, (_, k) => {
    const p = [0, 1, 2].map(j => ((k >> j) & 1) * size)
    return rotate ? [-p[1] + 3, p[0] - 2, p[2] + 7] : p
  }).flat())

describe('trajectory display interpolation', () => {
  it('passes through saved positions along a curved path with continuous knot tangents', () => {
    const p = [[0, 0, 0], [1, 1, 0], [2, 1, 0], [3, 0, 0], [4, 2, 0]]
    const out = new Float64Array(3), eps = .00001
    expect(Array.from(cubicCoordinates(...p.slice(0, 4), 0, out))).toEqual(p[1])
    expect(Array.from(cubicCoordinates(...p.slice(0, 4), 1, out))).toEqual(p[2])
    expect(cubicCoordinates(...p.slice(0, 4), .5, out)).toBe(out)
    expect(out[1]).toBeCloseTo(1.125)
    const left = Array.from(cubicCoordinates(...p.slice(0, 4), 1 - eps, out))
    const right = cubicCoordinates(...p.slice(1), eps, out)
    for (let j = 0; j < 3; j++) {
      expect((p[2][j] - left[j]) / eps).toBeCloseTo((right[j] - p[2][j]) / eps, 3)
    }
    expect(p[1]).toEqual([1, 1, 0])
  })

  it('does not borrow neighbours across stages or wrap from the last frame to the first', () => {
    expect(interpolationNeighbors(3, 4, 6, [{ frame: 3 }, { frame: 5 }])).toEqual({ before: null, after: null })
    expect(interpolationNeighbors(0, 1, 6)).toEqual({ before: null, after: 2 })
    expect(interpolationNeighbors(4, 5, 6)).toEqual({ before: 3, after: null })
  })

  it('unwraps all four ion frames before calculating spline tangents', () => {
    const before = [9.5, 4, 5], from = [9.8, 5, 5], to = [.2, 5, 5], after = [.8, 4, 5]
    const blend = periodicPositionInterpolator(from, to, box(), box(), { before, after, boxBefore: box(), boxAfter: box() })
    for (const t of [.25, .5, .75]) {
      const expected = cubicCoordinates(before, from, [10.2, 5, 5], [10.8, 4, 5], t)
      const actual = blend(t)
      expect(actual[0]).toBeCloseTo(expected[0] % 10, 5)
      expect(actual[1]).toBeCloseTo(expected[1], 5)
    }
    expect(blend(.5)[1]).toBeGreaterThan(5)
  })
  it('reuses display storage without modifying saved frames', () => {
    const a = new Float32Array([0, 1, 2]), b = new Float32Array([4, 5, 6])
    const out = lerpCoordinates(a, b, .25)
    expect(Array.from(out)).toEqual([1, 2, 3])
    expect(lerpCoordinates(a, b, .5, out)).toBe(out)
    expect(Array.from(a)).toEqual([0, 1, 2])
    expect(lerpCoordinates(a, [0], .5)).toBeNull()
  })

  it('wraps a crossing ion at the cell edge instead of through the pore', () => {
    const blend = periodicPositionInterpolator([9.8, 5, 5], [.2, 5, 5], box(), box())
    expect(blend(.25)[0]).toBeCloseTo(9.9)
    expect(blend(.75)[0]).toBeCloseTo(.1)
    expect(blend(1)[0]).toBeCloseTo(.2)
  })

  it('handles rotated, translated and breathing display cells', () => {
    const blend = periodicPositionInterpolator([-2, 7.8, 12], [-3, -1.76, 13], box(10, true), box(12, true))
    const mid = blend(.25)
    expect(mid[0]).toBeCloseTo(-2.25)
    expect(mid[1]).toBeCloseTo(8.395)
    expect(mid[2]).toBeCloseTo(12.25)
  })

  it('falls back to ordinary coordinates without a periodic cell', () => {
    expect(Array.from(periodicPositionInterpolator([0, 0, 0], [2, 4, 6])(.5))).toEqual([1, 2, 3])
  })
})
