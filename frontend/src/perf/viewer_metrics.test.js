import { expect, it } from 'vitest'
import { compareViewerMetrics, formatViewerMetrics, summarizeFrameIntervals } from './viewer_metrics.js'
import { createViewerCapture } from './viewer_capture.js'

it('reports tail stalls, excludes invalid samples, and never invents empty metrics', () => {
  const summary = summarizeFrameIntervals([10, 10, 10, 100, NaN, -1, 0])
  expect(summary).toMatchObject({ samples: 4, p50_ms: 10, p95_ms: 100, p99_ms: 100, worst_ms: 100, over_50ms: 1 })
  expect(summarizeFrameIntervals([]).p95_ms).toBeNull()
})

it('captures real intervals and marks cancellation separately from completion', () => {
  let time = 0
  let result
  const capture = createViewerCapture({ now: () => time, finish: record => { result = record } })
  capture.start({ duration_requested_ms: 1000 })
  expect(() => capture.start({ duration_requested_ms: 1000 })).toThrow('already running')
  capture.frame({ calls: 5 }, 100)
  time = 500; capture.frame({ calls: 6 }, 200)
  time = 1000; capture.frame({ calls: 7 }, 150)
  expect(result).toMatchObject({ valid: true, sampled_js_heap_peak_bytes: 200, render_counts_last_frame: { calls: 7 },
    frame_intervals: { samples: 2, p95_ms: 500 }, gpu_memory_bytes: null })
  capture.start({ duration_requested_ms: 1000 })
  capture.stop('Hidden tab')
  expect(result).toMatchObject({ valid: false, invalid_reason: 'Hidden tab', sampled_js_heap_peak_bytes: null })
})

it('refuses comparisons of mismatched workloads and retains machine-readable records', () => {
  const a = { valid: true, fixture_sha256: 'abc', scenario: 'orbit', environment: { viewport: [100, 100] },
    view: { representation: 'full' }, frame_intervals: { p95_ms: 10 } }
  const b = { ...a, frame_intervals: { p95_ms: 12 } }
  expect(compareViewerMetrics(a, b)).toMatchObject({ comparable: true, p95_delta_ms: 2 })
  expect(compareViewerMetrics(a, { ...b, fixture_sha256: 'other' })).toMatchObject({ comparable: false, p95_delta_ms: null })
  expect(compareViewerMetrics(a, { ...b, valid: false }).comparable).toBe(false)
  expect(formatViewerMetrics(a)).toBe(`[NADOC_VIEWER_PERF v1] ${JSON.stringify(a)}`)
})
