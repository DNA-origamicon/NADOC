import { describe, it, expect } from 'vitest'
import {
  NATURAL_SPACING_NM,
  RELAXED_SPACING_NM,
  spacingForExtraBases,
  maxExtraBaseCount,
  adjustedSpacingForDesign,
} from './extra_base_spacing.js'

describe('spacingForExtraBases', () => {
  it('returns the no-insert baseline for 0', () => {
    expect(spacingForExtraBases(0)).toBe(RELAXED_SPACING_NM[0])
  })

  it('widens monotonically with insert count', () => {
    expect(spacingForExtraBases(1)).toBeGreaterThan(spacingForExtraBases(0))
    expect(spacingForExtraBases(2)).toBeGreaterThan(spacingForExtraBases(1))
  })

  it('is sub-linear — the second base adds less than the first', () => {
    const d1 = spacingForExtraBases(1) - spacingForExtraBases(0)
    const d2 = spacingForExtraBases(2) - spacingForExtraBases(1)
    expect(d2).toBeLessThan(d1)
  })

  it('every relaxed value exceeds the caDNAno lattice pitch', () => {
    // Even a design with no inserts relaxes wider than it was built.
    for (const s of RELAXED_SPACING_NM) expect(s).toBeGreaterThan(NATURAL_SPACING_NM)
  })

  it('clamps above the measured range instead of extrapolating', () => {
    const last = RELAXED_SPACING_NM[RELAXED_SPACING_NM.length - 1]
    expect(spacingForExtraBases(3)).toBe(last)
    expect(spacingForExtraBases(17)).toBe(last)
  })

  it('treats negative and non-finite counts as no inserts', () => {
    expect(spacingForExtraBases(-1)).toBe(RELAXED_SPACING_NM[0])
    expect(spacingForExtraBases(NaN)).toBe(RELAXED_SPACING_NM[0])
    expect(spacingForExtraBases(undefined)).toBe(RELAXED_SPACING_NM[0])
  })

  it('floors fractional counts', () => {
    expect(spacingForExtraBases(1.9)).toBe(spacingForExtraBases(1))
  })
})

describe('maxExtraBaseCount', () => {
  it('is 0 for a design with no crossovers at all', () => {
    expect(maxExtraBaseCount({})).toBe(0)
    expect(maxExtraBaseCount(null)).toBe(0)
    expect(maxExtraBaseCount({ crossovers: [] })).toBe(0)
  })

  it('is 0 when every crossover is plain', () => {
    // extra_bases is Optional[str] on the wire — null, not "".
    expect(maxExtraBaseCount({ crossovers: [{ extra_bases: null }, {}] })).toBe(0)
  })

  it('counts string length, not truthiness', () => {
    expect(maxExtraBaseCount({ crossovers: [{ extra_bases: 'T' }] })).toBe(1)
    expect(maxExtraBaseCount({ crossovers: [{ extra_bases: 'TT' }] })).toBe(2)
  })

  it('takes the MAXIMUM over a mixed design, not the mode', () => {
    // The stated rule: a design mixing 1 and 2 is adjusted as if all were 2.
    const design = {
      crossovers: [
        { extra_bases: 'T' }, { extra_bases: 'T' }, { extra_bases: 'T' },
        { extra_bases: 'TT' },
        { extra_bases: null },
      ],
    }
    expect(maxExtraBaseCount(design)).toBe(2)
  })

  it('counts forced ligations too', () => {
    const design = {
      crossovers: [{ extra_bases: 'T' }],
      forced_ligations: [{ extra_bases: 'TTT' }],
    }
    expect(maxExtraBaseCount(design)).toBe(3)
  })

  it('survives a design where forced_ligations is absent or not an array', () => {
    expect(maxExtraBaseCount({ crossovers: [{ extra_bases: 'TT' }] })).toBe(2)
    expect(maxExtraBaseCount({ crossovers: [{ extra_bases: 'TT' }], forced_ligations: null })).toBe(2)
  })
})

describe('adjustedSpacingForDesign', () => {
  it('maps a mixed 1/2 design onto the 2-base spacing', () => {
    const design = { crossovers: [{ extra_bases: 'T' }, { extra_bases: 'TT' }] }
    expect(adjustedSpacingForDesign(design)).toBe(spacingForExtraBases(2))
  })

  it('gives an insert-free design the baseline correction, not the natural pitch', () => {
    const design = { crossovers: [{ extra_bases: null }] }
    expect(adjustedSpacingForDesign(design)).toBe(RELAXED_SPACING_NM[0])
    expect(adjustedSpacingForDesign(design)).toBeGreaterThan(NATURAL_SPACING_NM)
  })
})
