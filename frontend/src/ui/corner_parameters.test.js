import { expect, it } from 'vitest'
import { cornerParameters, cornerPositionStep, cornerPositionNm, cornerPositionBp, isNativeCornerFeature } from './corner_parameters.js'

it('exposes editing only for versioned native Corner features', () => {
  const entry = { feature_type: 'snapshot', op_kind: 'corner', params: { _proof_version: 1, operation_id: 'corner-op' } }
  expect(isNativeCornerFeature(entry)).toBe(true)
  expect(isNativeCornerFeature({ ...entry, params: { ...entry.params, _proof_version: 2 } })).toBe(true)
  expect(isNativeCornerFeature({ ...entry, params: { ...entry.params, _proof_version: 3 } })).toBe(true)
  expect(isNativeCornerFeature({ ...entry, params: { ...entry.params, _proof_version: 4 } })).toBe(false)
  expect(isNativeCornerFeature({ ...entry, op_kind: 'sweep' })).toBe(false)
  expect(isNativeCornerFeature({ ...entry, params: {} })).toBe(false)
  expect(isNativeCornerFeature(null)).toBe(false)
})

it('uses 8 bp square and 7 bp honeycomb increments', () => {
  expect(cornerPositionStep('SQUARE')).toBe(8)
  expect(cornerPositionStep('HONEYCOMB')).toBe(7)
  expect(() => cornerPositionStep('unknown')).toThrow()
})

it('converts physical position to the nearest nucleotide station', () => {
  expect(cornerPositionNm(8)).toBeCloseTo(2.672)
  expect(cornerPositionBp(2.672)).toBe(8)
  expect(cornerPositionBp(2.7)).toBe(8)
  expect(() => cornerPositionBp(Infinity)).toThrow()
})

it('preserves zero angle and normalizes the local compass direction', () => {
  expect(cornerParameters({ positionBp: -4, angleDeg: 0, directionDeg: -15 }))
    .toEqual({ positionBp: -4, angleDeg: 0, directionDeg: 345 })
  for (const patch of [{ positionBp: 1.2 }, { angleDeg: 180 }, { angleDeg: NaN }, { directionDeg: Infinity }]) {
    expect(() => cornerParameters({ positionBp: 42, angleDeg: 90, directionDeg: 0, ...patch })).toThrow()
  }
})
