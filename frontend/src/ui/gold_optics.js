import data from '../../../backend/data/photophysics/gold_optics.json'

export const GOLD_OPTICS = data
// nm² → cm², then single-particle cross section → decadic molar coefficient.
export const crossSectionToMolar = crossSection => crossSection * 1e-14 * 6.02214076e23 / (1000 * Math.LN10)
export const vendorMolar = row => row[2] * 6.02214076e23 / (1000 * row[3])

export function goldOptics(diameter) {
  if (!Number.isFinite(diameter) || diameter < 5 || diameter > 100) return null
  const low = data.spectra[Math.floor(diameter) - 5]
  const high = data.spectra[Math.ceil(diameter) - 5]
  const fraction = diameter - Math.floor(diameter)
  const interpolate = key => low[key].map((value, i) => value + fraction * (high[key][i] - value))
  const extinction = interpolate('extinction_nm2'), absorption = interpolate('absorption_nm2')
  const peak = extinction.indexOf(Math.max(...extinction))
  const absorptionPeak = absorption.indexOf(Math.max(...absorption))
  return { wavelength: data.wavelength_nm, extinction, absorption,
    scattering: extinction.map((value, i) => Math.max(0, value - absorption[i])),
    peakNm: data.wavelength_nm[peak], absorptionPeakNm: data.wavelength_nm[absorptionPeak],
    epsilon: crossSectionToMolar(extinction[peak]), interpolated: fraction !== 0 }
}
