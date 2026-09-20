import { getViewerPerformance } from '../perf/viewer_performance.js'
import { formatViewerMetrics } from '../perf/viewer_metrics.js'

/** Mount inside Process Log. Capturing survives closing the log; rendering it does not. */
export function mountViewerPerformancePanel(container, onStart = () => {}) {
  const api = getViewerPerformance()
  if (!api) return () => {}
  const section = document.createElement('details')
  section.className = 'viewer-performance-controls'
  section.innerHTML = `<summary>Performance comparison</summary>
    <p>Frame timing only: load the design and wait for its representation to finish first.
    Orbit repeats a 20-second revolution from your saved viewpoint. Freeform records your own gestures or playback.
    Use the same file, camera, quality, window size and device for A and B. Close this log during capture.</p>
    <div class="process-log-controls">
      <label>Variant <select data-perf-variant aria-label="Performance variant"><option>A</option><option>B</option></select></label>
      <label>Scenario <select data-perf-scenario aria-label="Performance scenario"><option value="orbit">Repeatable orbit</option><option value="freeform">Freeform / playback</option></select></label>
      <label>Seconds <input data-perf-seconds aria-label="Capture seconds" type="number" min="1" max="60" value="20"></label>
      <button type="button" data-perf-pose>Use current viewpoint</button>
      <button type="button" data-perf-start>Start capture</button>
      <button type="button" data-perf-stop>Stop capture</button>
    </div><p data-perf-status role="status"></p>
    <button type="button" data-perf-copy>Copy latest metrics</button>
    <textarea data-perf-output aria-label="Copyable performance metrics" readonly rows="4"></textarea>`
  container.append(section)
  const query = selector => section.querySelector(selector)
  query('[data-perf-variant]').value = api.defaultVariant ?? 'A'
  const status = query('[data-perf-status]')
  const output = query('[data-perf-output]')
  function render() {
    query('[data-perf-start]').disabled = api.busy
    query('[data-perf-stop]').disabled = !api.busy
    query('[data-perf-pose]').disabled = api.busy
    query('[data-perf-copy]').disabled = !api.latest
    status.textContent = api.busy ? 'Capture running or preparing. Close Process Log and keep this tab visible.'
      : api.latest ? `${api.latest.valid ? 'Completed' : 'Invalid'}: ${api.latest.invalid_reason ?? `${api.latest.frame_intervals.samples} frame intervals recorded`}`
        : 'A labels the baseline; B labels the candidate. A label does not switch renderer implementations.'
    if (api.latest) output.value = formatViewerMetrics(api.latest)
  }
  query('[data-perf-start]').onclick = async () => {
    try {
      await api.start({ variant: query('[data-perf-variant]').value,
        scenario: query('[data-perf-scenario]').value,
        durationMs: Number(query('[data-perf-seconds]').value) * 1000 })
      onStart()
    } catch (error) { status.textContent = error.message }
  }
  query('[data-perf-stop]').onclick = () => api.stop()
  query('[data-perf-pose]').onclick = () => { api.resetPose(); status.textContent = 'The next orbit will start from the current viewpoint.' }
  query('[data-perf-copy]').onclick = async () => {
    output.focus(); output.select()
    try {
      await navigator.clipboard.writeText(output.value)
      status.textContent = 'Metrics copied. Paste them with the other variant for comparison.'
    } catch { status.textContent = 'Metrics selected below. Use your normal Copy command.' }
  }
  const unsubscribe = api.subscribe(render)
  render()
  return () => { unsubscribe(); section.remove() }
}
