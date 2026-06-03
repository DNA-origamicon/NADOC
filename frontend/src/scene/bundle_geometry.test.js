import { describe, it, expect } from 'vitest'
import { bundleAxisRange, bundleMaxOffset, bundleMidOffset } from './bundle_geometry.js'

// Build a helix with explicit axis endpoints. Only axis_start/axis_end are read.
const helix = (start, end) => ({ axis_start: start, axis_end: end })
const designOf = (...helices) => ({ helices })

describe('bundleAxisRange', () => {
  it('returns {0,0} for a null or helix-less design', () => {
    expect(bundleAxisRange(null, 'XY')).toEqual({ min: 0, max: 0 })
    expect(bundleAxisRange(undefined, 'XY')).toEqual({ min: 0, max: 0 })
    expect(bundleAxisRange(designOf(), 'XY')).toEqual({ min: 0, max: 0 })
  })

  it('XY plane uses the z extent', () => {
    const d = designOf(helix({ x: 0, y: 0, z: 2 }, { x: 9, y: 9, z: 7 }))
    expect(bundleAxisRange(d, 'XY')).toEqual({ min: 2, max: 7 })
  })

  it('XZ plane uses the y extent', () => {
    const d = designOf(helix({ x: 0, y: 3, z: 0 }, { x: 9, y: 8, z: 9 }))
    expect(bundleAxisRange(d, 'XZ')).toEqual({ min: 3, max: 8 })
  })

  it('any other plane (e.g. YZ) uses the x extent', () => {
    const d = designOf(helix({ x: 1, y: 9, z: 9 }, { x: 6, y: 0, z: 0 }))
    expect(bundleAxisRange(d, 'YZ')).toEqual({ min: 1, max: 6 })
  })

  it('handles axis_start > axis_end via min/max per helix', () => {
    // x descends from 10 to 4 within the helix; range should still be {4,10}.
    const d = designOf(helix({ x: 10, y: 0, z: 0 }, { x: 4, y: 0, z: 0 }))
    expect(bundleAxisRange(d, 'YZ')).toEqual({ min: 4, max: 10 })
  })

  it('spans the min/max across multiple helices', () => {
    const d = designOf(
      helix({ x: 0, y: 0, z: -5 }, { x: 0, y: 0, z: -1 }),
      helix({ x: 0, y: 0, z: 3 }, { x: 0, y: 0, z: 8 }),
    )
    expect(bundleAxisRange(d, 'XY')).toEqual({ min: -5, max: 8 })
  })
})

describe('bundleMaxOffset / bundleMidOffset', () => {
  const d = designOf(
    helix({ x: 0, y: 0, z: -4 }, { x: 0, y: 0, z: -4 }),
    helix({ x: 0, y: 0, z: 10 }, { x: 0, y: 0, z: 10 }),
  )

  it('bundleMaxOffset returns the max of the range', () => {
    expect(bundleMaxOffset(d, 'XY')).toBe(10)
  })

  it('bundleMidOffset returns the midpoint of the range', () => {
    expect(bundleMidOffset(d, 'XY')).toBe(3) // (-4 + 10) / 2
  })

  it('both return 0 for an empty design', () => {
    expect(bundleMaxOffset(designOf(), 'XY')).toBe(0)
    expect(bundleMidOffset(designOf(), 'XY')).toBe(0)
  })
})
