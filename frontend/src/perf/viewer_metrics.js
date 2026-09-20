/** Portable measurements; no renderer, editor, or browser ownership here. */
export const VIEWER_PERF_PREFIX = '[NADOC_VIEWER_PERF v1]'

export function summarizeFrameIntervals(intervals) {
  const values = intervals.filter(value => Number.isFinite(value) && value > 0).sort((a, b) => a - b)
  const percentile = fraction => values.length ? values[Math.ceil(values.length * fraction) - 1] : null
  return {
    samples: values.length,
    p50_ms: percentile(0.5), p95_ms: percentile(0.95), p99_ms: percentile(0.99),
    worst_ms: values.at(-1) ?? null,
    over_33ms: values.filter(value => value > 33.333).length,
    over_50ms: values.filter(value => value > 50).length,
    mean_fps: values.length ? 1000 * values.length / values.reduce((sum, value) => sum + value, 0) : null,
  }
}

export function formatViewerMetrics(record) {
  return `${VIEWER_PERF_PREFIX} ${JSON.stringify(record)}`
}

/** A comparison must describe the same workload; changed fixtures are not regressions. */
export function compareViewerMetrics(a, b) {
  const reasons = []
  if (!a.valid || !b.valid) reasons.push('A run was invalid or interrupted')
  if (!a.fixture_sha256 || a.fixture_sha256 !== b.fixture_sha256) reasons.push('Fixture hashes differ or are unavailable')
  if (a.scenario !== 'orbit' || b.scenario !== 'orbit') reasons.push('Freeform captures need manual workload comparison')
  for (const key of ['schema', 'instrumentation', 'build_mode', 'cache', 'scenario', 'duration_requested_ms', 'environment', 'view']) {
    if (JSON.stringify(a[key]) !== JSON.stringify(b[key])) reasons.push(`${key} differs`)
  }
  const before = a.frame_intervals?.p95_ms
  const after = b.frame_intervals?.p95_ms
  return {
    comparable: !reasons.length, reasons,
    p95_delta_ms: !reasons.length && before > 0 && Number.isFinite(after) ? after - before : null,
    p95_delta_percent: !reasons.length && before > 0 && Number.isFinite(after) ? 100 * (after / before - 1) : null,
  }
}
