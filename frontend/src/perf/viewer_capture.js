import { summarizeFrameIntervals } from './viewer_metrics.js'

/** A capture is active only on request. The host calls frame() once per actual frame. */
export function createViewerCapture({ now = () => performance.now(), finish }) {
  let active = null
  function stop(reason = null) {
    if (!active) return null
    const run = active
    active = null
    const record = {
      ...run.metadata,
      elapsed_ms: now() - run.started,
      valid: !reason && run.intervals.length >= 2,
      invalid_reason: reason ?? (run.intervals.length < 2 ? 'Insufficient rendered frames' : null),
      frame_intervals: summarizeFrameIntervals(run.intervals),
      render_counts_last_frame: run.counts,
      sampled_js_heap_peak_bytes: run.heapPeak,
      heap_method: run.heapPeak === null ? 'unavailable' : 'performance.memory.usedJSHeapSize (sampled, approximate)',
      gpu_memory_bytes: null,
    }
    finish(record)
    return record
  }
  return {
    start(metadata) {
      if (active) throw new Error('A viewer capture is already running')
      if (!(metadata.duration_requested_ms >= 1000 && metadata.duration_requested_ms <= 60000)) throw new Error('Invalid capture duration')
      active = { metadata, started: now(), previous: null, intervals: [], counts: null, heapPeak: null }
    },
    frame(counts, heapBytes = null) {
      if (!active) return
      const time = now()
      if (active.previous !== null) active.intervals.push(time - active.previous)
      active.previous = time
      active.counts = counts
      if (Number.isFinite(heapBytes) && heapBytes >= 0) active.heapPeak = Math.max(active.heapPeak ?? 0, heapBytes)
      if (time - active.started >= active.metadata.duration_requested_ms) stop()
    },
    stop,
    get active() { return !!active },
  }
}
