import { describe, it, expect } from 'vitest'
import {
  floorNormal, floorSurfaceSpec, floorSpecReady, formatOffsetNm, FLOOR_AXIS_NORMALS,
  axisForNormal, floorContactCoordinate, floorClearanceFromAbsolute, floorAbsoluteFromClearance,
} from './oxdna_floor_math.js'

describe('axisForNormal', () => {
  it('inverts floorNormal for every side', () => {
    for (const axis of Object.keys(FLOOR_AXIS_NORMALS)) {
      expect(axisForNormal(floorNormal(axis))).toBe(axis)
    }
  })
  it('picks the closest side for an off-axis / non-unit vector', () => {
    expect(axisForNormal([0, 3.2, 0])).toBe('-y')   // points up → floor below
    expect(axisForNormal([0.1, 0.9, 0])).toBe('-y')
  })
  it('returns null for a missing/zero vector', () => {
    expect(axisForNormal(null)).toBeNull()
    expect(axisForNormal([0, 0, 0])).toBeNull()
  })
})

describe('floorNormal', () => {
  it('returns the outward unit normal for each side', () => {
    expect(floorNormal('-y')).toEqual([0, 1, 0])
    expect(floorNormal('+y')).toEqual([0, -1, 0])
    expect(floorNormal('-x')).toEqual([1, 0, 0])
    expect(floorNormal('+x')).toEqual([-1, 0, 0])
    expect(floorNormal('-z')).toEqual([0, 0, 1])
    expect(floorNormal('+z')).toEqual([0, 0, -1])
  })
  it('every mapped normal is a unit vector', () => {
    for (const n of Object.values(FLOOR_AXIS_NORMALS)) {
      expect(Math.hypot(...n)).toBeCloseTo(1, 12)
    }
  })
  it('returns null for off / unknown', () => {
    expect(floorNormal('off')).toBeNull()
    expect(floorNormal(undefined)).toBeNull()
    expect(floorNormal('diagonal')).toBeNull()
  })
  it('returns a copy (caller cannot mutate the table)', () => {
    const n = floorNormal('-y')
    n[0] = 99
    expect(FLOOR_AXIS_NORMALS['-y']).toEqual([0, 1, 0])
  })
})

describe('floorSurfaceSpec', () => {
  it('is null when the axis is unknown', () => {
    expect(floorSurfaceSpec({ axis: 'off', stiff: 5 })).toBeNull()
    expect(floorSurfaceSpec({ axis: 'bogus' })).toBeNull()
  })
  it('assembles dir + offset + stiff for a valid side', () => {
    const spec = floorSurfaceSpec({ axis: '-y', offsetNm: 2.5, stiff: 5 })
    expect(spec.dir).toEqual([0, 1, 0])
    expect(spec.offsetNm).toBe(2.5)
    expect(spec.stiff).toBe(5)
    expect(spec.anchors).toBeUndefined()       // anchors are a separate element now
  })
  it('clamps a negative stiffness to 0 and coerces junk numbers', () => {
    const spec = floorSurfaceSpec({ axis: '+x', offsetNm: 'nope', stiff: -3 })
    expect(spec.offsetNm).toBe(0)
    expect(spec.stiff).toBe(0)
  })
})

describe('floorSpecReady', () => {
  const base = () => ({ dir: [0, 1, 0], offsetNm: 0, stiff: 5 })
  it('true for a complete spec (no anchor required — bare wall is valid)', () => {
    expect(floorSpecReady(base())).toBe(true)
  })
  it('false without a normal', () => {
    expect(floorSpecReady(null)).toBe(false)
    expect(floorSpecReady({ ...base(), dir: [0, 0, 0] })).toBe(false)
  })
  it('false with zero stiffness', () => {
    expect(floorSpecReady({ ...base(), stiff: 0 })).toBe(false)
  })
})

describe('formatOffsetNm', () => {
  it('formats to one decimal with a nm suffix', () => {
    expect(formatOffsetNm(0)).toBe('0.0 nm')
    expect(formatOffsetNm(2.5)).toBe('2.5 nm')
    expect(formatOffsetNm(-3.25)).toBe('-3.3 nm')
  })
  it('coerces junk to 0.0', () => {
    expect(formatOffsetNm('x')).toBe('0.0 nm')
  })
})

describe('absolute surface positioning', () => {
  const bounds = { min: [-8, -3, -5], max: [12, 7, 9] }
  it('selects the contact face for each side', () => {
    expect(floorContactCoordinate('-x', bounds)).toBe(-8)
    expect(floorContactCoordinate('+x', bounds)).toBe(12)
    expect(floorContactCoordinate('-y', bounds)).toBe(-3)
    expect(floorContactCoordinate('+z', bounds)).toBe(9)
  })
  it('round-trips absolute coordinates through backend clearance semantics', () => {
    expect(floorClearanceFromAbsolute('-y', -5, bounds)).toBe(2)
    expect(floorAbsoluteFromClearance('-y', 2, bounds)).toBe(-5)
    expect(floorClearanceFromAbsolute('+y', 10, bounds)).toBe(3)
    expect(floorAbsoluteFromClearance('+y', 3, bounds)).toBe(10)
  })
})
