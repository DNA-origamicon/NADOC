import { describe, expect, it } from 'vitest'
import { GOLD_OPTICS, goldOptics, crossSectionToMolar, vendorMolar } from './gold_optics.js'

describe('gold optical reference', () => {
  it('preserves energy balance throughout the bundled size/wavelength grid', () => {
    for (const row of GOLD_OPTICS.spectra) {
      expect(row.extinction_nm2).toHaveLength(GOLD_OPTICS.wavelength_nm.length)
      row.extinction_nm2.forEach((value, i) => {
        expect(value).toBeGreaterThan(0)
        expect(row.absorption_nm2[i]).toBeGreaterThanOrEqual(0)
        expect(row.absorption_nm2[i]).toBeLessThanOrEqual(value)
      })
    }
  })
  it('converts cross section to decadic molar extinction per mole of particles', () => {
    expect(crossSectionToMolar(1)).toBeCloseTo(2615382.505)
    expect(vendorMolar([10, 520, 16.4, 9.88e13])).toBeCloseTo(99962660.388664)
  })
  it('interpolates fractional size and rejects sizes outside the reference range', () => {
    const a = goldOptics(10), b = goldOptics(11), middle = goldOptics(10.5)
    expect(middle.interpolated).toBe(true)
    expect(middle.extinction[50]).toBeCloseTo((a.extinction[50] + b.extinction[50]) / 2)
    for (const value of [null, NaN, 0, 4.9, 100.1, 1000]) expect(goldOptics(value)).toBeNull()
    expect(goldOptics(100).peakNm).toBeGreaterThan(a.peakNm)
  })
})
