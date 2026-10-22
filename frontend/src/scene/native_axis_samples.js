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

// Resolve an interval in its own domain frame, never the whole-helix chord.
export function segmentAxisEndpoints(axis, segment, lo = segment.bp_lo, hi = segment.bp_hi) {
  const source = axis?.segments?.find(s => s.strand_id === segment.strandId && s.domain_index === segment.domainIndex
    && s.bp_lo <= lo && s.bp_hi >= hi)
  if (!source) return null
  const span = source.bp_hi - source.bp_lo + 1
  const at = bp => source.start.map((v, i) => v + (source.end[i] - v) * (bp - source.bp_lo) / span)
  return [at(lo), at(hi + 1)]
}
