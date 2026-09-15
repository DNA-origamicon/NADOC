import { describe, it, expect } from 'vitest'
import { Vector3 } from 'three'
import { GOLD_QUENCHING_DATA, goldQuenchingProfile, evaluateGoldQuenching, transferRate } from './gold_quenching.js'

const donor = { modification: 'fam', pos: new Vector3(0, 0, 0) }
const gold = (x = 12.12, diameter = 3, id = 'gold') => ({ id, kind: 'gold_nanosphere', diameter_nm: diameter, pos: new Vector3(x, 0, 0) })

describe('gold quenching reference data and geometry', () => {
  it('converts experimental gold radius to diameter and angstrom d0 to nm', () => {
    expect(goldQuenchingProfile('fam', 1.89).d0_nm).toBe(7.25)
    expect(goldQuenchingProfile('fam', 16.5).d0_nm).toBe(32.08)
    expect(goldQuenchingProfile('cy3b', 8).d0_nm).toBe(16)
    expect(goldQuenchingProfile('cy3', 8)).toBeNull()
  })
  it('interpolates size explicitly and never extrapolates or aliases donors', () => {
    expect(goldQuenchingProfile('fam', 2.445)).toMatchObject({ interpolated: true, d0_nm: (7.25 + 10.62) / 2 })
    for (const diameter of [0, 1.5, 16.51, 30, NaN, Infinity]) expect(goldQuenchingProfile('fam', diameter)).toBeNull()
    expect(goldQuenchingProfile('quantum_dot', 3)).toBeNull()
  })
  it('uses donor-center to gold-surface, yielding half brightness at d0', () => {
    const result = evaluateGoldQuenching(donor, [gold()])
    expect(result.brightness).toBeCloseTo(0.5)
    expect(result.pairs[0].distanceNm).toBeCloseTo(10.62)
    expect(result.pairs[0].quenching).toBeCloseTo(0.5)
    expect(result.incomplete).toBe(false)
  })
  it('is continuous beyond d0, rather than an on/off radius threshold', () => {
    expect(evaluateGoldQuenching(donor, [gold(1.5 + 2 * 10.62)]).brightness).toBeCloseTo(16 / 17)
    expect(evaluateGoldQuenching(donor, [gold(1.5 + 10.62 / 2)]).brightness).toBeCloseTo(1 / 17)
  })
  it('adds independent rates, not efficiencies or brightness products', () => {
    const result = evaluateGoldQuenching(donor, [gold(), gold(-12.12, 3, 'second')])
    expect(result.brightness).toBeCloseTo(1 / 3)
  })
  it('distinguishes unknown pairs and collisions from zero quenching', () => {
    for (const particle of [gold(100, 30), gold(0), gold(1.5)]) {
      const result = evaluateGoldQuenching(donor, [particle])
      expect(result.incomplete).toBe(true)
      expect(result.pairs[0].quenching).toBeNull()
      expect(result.brightness).toBe(1)
    }
    const mixed = evaluateGoldQuenching(donor, [gold(), gold(100, 30, 'unsupported')])
    expect(mixed.incomplete).toBe(true)
    expect(mixed.brightness).toBeCloseTo(0.5)
  })
  it('never assigns dye data to a QD with a matching color or emission peak', () => {
    const dot = { ...donor, kind: 'quantum_dot', diameter_nm: 8, quantum_dot: { emission_peak_nm: 520 } }
    const result = evaluateGoldQuenching(dot, [gold()])
    expect(result.pairs[0].reason).toBe('QD–gold pair not calibrated')
    expect(result.pairs[0].distanceNm).toBeCloseTo(10.62) // NOT 6.62: emitter is at dot center
    expect(result.pairs[0].quenching).toBeNull()
    expect(evaluateGoldQuenching(dot, [gold(5)]).pairs[0].reason).toContain('overlap')
  })
  it('does not silently reuse reference dye curves for a new protein coating', () => {
    const result = evaluateGoldQuenching(donor, [{ ...gold(), coating: { kind: 'streptavidin' } }])
    expect(result.pairs[0].reason).toBe('Streptavidin-coated gold pair not calibrated')
    expect(result.pairs[0].quenching).toBeNull()
  })
  it('retains QD evidence without enabling an unverified geometric convention', () => {
    const evidence = GOLD_QUENCHING_DATA.evidence.find(e => e.reported_half_quenching_nm)
    expect(evidence).toMatchObject({ reported_half_quenching_nm: 28, exponent: 2.7, render_enabled: false })
  })
  it('rejects invalid inputs and handles the zero-distance rate limit', () => {
    expect(transferRate(0, 5, 4)).toBe(Infinity)
    expect(transferRate(5, 5, 4)).toBe(1)
    for (const value of [NaN, -1, Infinity]) expect(transferRate(value, 5, 4)).toBeNull()
    expect(evaluateGoldQuenching(donor, []).brightness).toBe(1)
  })
})
