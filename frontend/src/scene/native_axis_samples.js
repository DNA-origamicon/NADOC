// Same local bp sampling as backend/core/deformation.py.
export function segmentAxisSamples(helix, segment, samples, start, end, step = 7) {
  const points = [start]
  if (samples?.length > 2) {
    const lo = segment.bp_lo - helix.bp_start, hi = segment.bp_hi - helix.bp_start
    for (let i = 0; i < samples.length; i++) {
      const bp = i === samples.length - 1 ? helix.length_bp - 1 : i * step
      if (bp > lo && bp <= hi) points.push(samples[i])
    }
  }
  points.push(end)
  return points
}
