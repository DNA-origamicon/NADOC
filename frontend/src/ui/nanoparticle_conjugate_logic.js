export const THIOL_SCHEMES = [
  ['direct_thiol', 'Direct thiol–DNA'],
  ['alkyl_thiol', 'Alkyl-spaced thiol–DNA'],
  ['peg_thiol', 'Thiol–PEG–DNA'],
  ['peg_backfill', 'Thiol–DNA + PEG-thiol backfill'],
]

export function sliderCount(step, capacity) {
  const exact = [1, 2, 3, 5, 10]
  if (step < exact.length) return Math.min(capacity, exact[step])
  return Math.max(1, Math.round(capacity * [0.25, 0.5, 0.75, 1][step - exact.length]))
}

export function countSliderStep(count, capacity) {
  let best = 0, distance = Infinity
  for (let step = 0; step <= 8; step++) {
    const d = Math.abs(sliderCount(step, capacity) - count)
    if (d < distance) { best = step; distance = d }
  }
  return best
}

/** Normalize direct numeric entry without treating the literature estimate as
 * a ceiling. The API's 10,000-strand safety bound remains the only hard cap. */
export function manualStrandCount(value) {
  return Math.min(10000, Math.max(1, Math.round(Number(value) || 1)))
}

export function conjugationSummary(count, estimate) {
  const area = estimate?.surface_area_nm2 || 1
  return {
    count,
    density: count / area,
    spacing: Math.sqrt(area / count),
    capacity: estimate?.estimated_capacity || 1,
  }
}
