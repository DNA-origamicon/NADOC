import { expect, it } from 'vitest'
import { bevelParameters, bevelPositionBp, bevelPositionNm, bevelPositionStep, isNativeBevelFeature } from './bevel_parameters.js'
it('uses perpendicular zero, a strict oblique limit, and explicit retained-side semantics', () => {
  expect(bevelParameters({ positionBp: 42, angleDeg: 0, directionDeg: -15, trimEnd: 'start' }))
    .toEqual({ positionBp: 42, angleDeg: 0, directionDeg: 345, trimEnd: 'start' })
  for (const patch of [{ angleDeg: 90 }, { angleDeg: -1 }, { positionBp: 1.5 }, { trimEnd: 'both' }, { directionDeg: NaN }])
    expect(() => bevelParameters({ positionBp: 42, angleDeg: 30, directionDeg: 0, ...patch })).toThrow()
})
it('links bp/nm and keeps lattice spinner increments', () => {
  expect(bevelPositionBp(bevelPositionNm(83))).toBe(83)
  expect(bevelPositionStep('SQUARE')).toBe(8)
  expect(bevelPositionStep('HONEYCOMB')).toBe(7)
  expect(() => bevelPositionStep('OTHER')).toThrow()
  expect(() => bevelPositionBp(Infinity)).toThrow()
})
it('only admits native bevel history', () => {
  const entry = { feature_type: 'snapshot', op_kind: 'bevel', params: { _proof_version: 1, operation_id: 'cut' } }
  expect(isNativeBevelFeature(entry)).toBe(true)
  expect(isNativeBevelFeature({ ...entry, op_kind: 'corner' })).toBe(false)
  expect(isNativeBevelFeature({ ...entry, params: {} })).toBe(false)
})
