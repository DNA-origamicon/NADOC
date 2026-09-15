import catalog from '../../../backend/data/photophysics/gold_quenching.json'

export const GOLD_QUENCHING_DATA = catalog

/** Empirical NSET distances. Deliberately no dye aliases or size extrapolation. */
export function goldQuenchingProfile(donor, diameter) {
  const profile = catalog.profiles.find(p => p.donor === donor)
  if (!profile || !Number.isFinite(diameter)) return null
  const points = profile.points
  if (diameter < points[0].gold_diameter_nm || diameter > points.at(-1).gold_diameter_nm) return null
  const upper = points.findIndex(p => p.gold_diameter_nm >= diameter)
  const right = points[upper]
  if (right.gold_diameter_nm === diameter) return { ...profile, d0_nm: right.d0_nm, interpolated: false }
  const left = points[upper - 1]
  const fraction = (diameter - left.gold_diameter_nm) / (right.gold_diameter_nm - left.gold_diameter_nm)
  return { ...profile, d0_nm: left.d0_nm + fraction * (right.d0_nm - left.d0_nm), interpolated: true }
}

/** Rate relative to the unquenched donor decay rate; 1 means 50% quenching. */
export function transferRate(distance, d0, exponent) {
  if (![distance, d0, exponent].every(Number.isFinite) || distance < 0 || d0 <= 0 || exponent <= 0) return null
  return distance === 0 ? Infinity : (d0 / distance) ** exponent
}

/** Unknown pairs are preserved in diagnostics, not misreported as E=0. */
export function evaluateGoldQuenching(donor, goldParticles) {
  const pairs = goldParticles.map(gold => {
    const distance = donor.pos.distanceTo(gold.pos) - gold.diameter_nm / 2
    const overlap = distance <= (donor.diameter_nm ?? 0) / 2
    const profile = goldQuenchingProfile(donor.kind === 'quantum_dot' ? null : donor.modification, gold.diameter_nm)
    const reason = !Number.isFinite(distance) ? 'Invalid geometry'
      : overlap ? 'Contact/overlap: outside the transfer model'
      : gold.coating ? 'Streptavidin-coated gold pair not calibrated'
      : !profile ? donor.kind === 'quantum_dot' ? 'QD–gold pair not calibrated' : 'No calibration for this dye / gold size'
      : null
    const rate = reason ? null : transferRate(distance, profile.d0_nm, profile.exponent)
    return { goldId: gold.id, goldDiameterNm: gold.diameter_nm, distanceNm: distance,
      profile, reason, rate, quenching: rate === null ? null : 1 - 1 / (1 + rate) }
  })
  const rate = pairs.reduce((sum, p) => sum + (p.rate ?? 0), 0)
  return { donor, pairs, rate, brightness: 1 / (1 + rate), incomplete: pairs.some(p => p.rate === null) }
}
