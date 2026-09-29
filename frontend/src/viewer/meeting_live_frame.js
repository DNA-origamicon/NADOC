import { LIVE_FRAME_LIMITS } from './live_frame_capture.js'
import { liveTimeline, mountLiveTimeline } from './live_timeline.js'
import { createClipApplier, gzipFrame } from './trajectory_clip.js'

/** Coalesce slow connections to the newest absolute frame; never queue a movie. */
export function mountMeetingLiveFrame({ viewer, base, revision, fetch: request = fetch, document: doc = document,
  now = () => performance.now(), setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  const current = viewer.current, status = doc.createElement('span')
  status.dataset.liveFrameStatus = ''; status.setAttribute('role', 'status')
  doc.body.insertBefore(status, doc.querySelector('main'))
  const timeline = mountLiveTimeline(doc)
  const smoothLabel = doc.createElement('label')
  smoothLabel.innerHTML = '<input data-live-smooth type="checkbox" checked> Smooth playback'
  smoothLabel.title = 'Smooth between received snapshots with a short display delay. Pausing displays the exact received frame.'
  smoothLabel.hidden = true
  status.after(smoothLabel)
  const smooth = smoothLabel.querySelector('input')
  let latest = null, shown = -1, flight = null, disposed = false, apply = null, retryAt = 0
  let displayed = null, pending = null, segment = null, receivedAt = null
  function exact(sample) {
    apply.apply(sample.raw); timeline.update(sample.timeline); displayed = sample; segment = null
  }
  function animate() {
    if (disposed || viewer.current !== current || (doc.hidden && !viewer.runtime?.renderer.xr.isPresenting) || viewer.performanceApi?.busy) return
    let nextStart = now()
    if (segment) {
      const t = Math.min(1, (now() - segment.at) / segment.duration)
      if (t >= 1) { nextStart = segment.at + segment.duration; exact(segment.to) }
      else apply.interpolate(displayed.raw, segment.to.raw, t)
    }
    if (!segment && pending) {
      const next = pending; pending = null
      if (smooth.checked && displayed?.timeline?.playing && next.timeline?.playing &&
        displayed.timeline.total === next.timeline.total && next.timeline.frame >= displayed.timeline.frame) {
        segment = { to: next, at: Math.max(nextStart, now() - next.duration), duration: next.duration }
        const t = Math.min(1, (now() - segment.at) / segment.duration)
        if (t > 0) apply.interpolate(displayed.raw, segment.to.raw, t)
      } else exact(next)
    }
  }
  smooth.onchange = () => {
    if (!smooth.checked) {
      const next = pending ?? segment?.to
      pending = null
      if (next) exact(next)
    }
  }
  async function tick() {
    if (disposed || (doc.hidden && !viewer.runtime?.renderer.xr.isPresenting) || flight || !latest || latest.sequence <= shown || viewer.current !== current || Date.now() < retryAt) return
    const frame = latest, abort = new AbortController(); flight = abort
    timeline.setBuffering(true, frame.timeline)
    try {
      const response = await request(`${base}/live-frame?revision=${revision}&sequence=${frame.sequence}`, { signal: abort.signal })
      if (response.status === 409) return
      if (!response.ok) throw new Error('Trajectory connection interrupted')
      const delivered = response.headers.get('X-NADOC-Sequence')
        ? { timeline: JSON.parse(response.headers.get('X-NADOC-Timeline') ?? 'null'), sequence: Number(response.headers.get('X-NADOC-Sequence')), bytes: Number(response.headers.get('Content-Length')), sha256: response.headers.get('X-NADOC-SHA256') } : frame
      if (!Number.isSafeInteger(delivered.sequence) || delivered.sequence < frame.sequence || !Number.isSafeInteger(delivered.bytes) || delivered.bytes < 1 || !/^[a-f0-9]{64}$/.test(delivered.sha256)) throw new Error('Invalid streamed frame header')
      if (Number(response.headers.get('Content-Length')) !== delivered.bytes) throw new Error('Invalid streamed frame length')
      const deliveredTimeline = liveTimeline(delivered.timeline)
      const buffer = await response.arrayBuffer()
      if (buffer.byteLength !== delivered.bytes) throw new Error('Incomplete streamed frame')
      const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(b => b.toString(16).padStart(2, '0')).join('')
      if (digest !== delivered.sha256) throw new Error('Streamed frame identity mismatch')
      const raw = await gzipFrame(buffer, true, LIVE_FRAME_LIMITS)
      if (disposed || abort.signal.aborted || viewer.current !== current) return
      apply ??= createClipApplier(current, LIVE_FRAME_LIMITS)
      const time = now(), sample = { raw, timeline: deliveredTimeline, duration: receivedAt === null ? 125 : Math.max(33, Math.min(500, time - receivedAt)) }
      receivedAt = time
      smoothLabel.hidden = !deliveredTimeline
      // A pause/seek replaces any interpolation immediately. While playing, keep
      // only the newest pending sample, plus the two displayed endpoints.
      if (!deliveredTimeline?.playing || !smooth.checked || !displayed ||
        deliveredTimeline.total !== displayed.timeline?.total || deliveredTimeline.frame < displayed.timeline.frame) {
        pending = null; exact(sample)
      } else { pending = sample; animate() }
      shown = delivered.sequence; status.textContent = ''
      const viewStatus = doc.getElementById('status')
      if (viewStatus) viewStatus.textContent = 'Shared visualization · Orbit, pan and zoom · Double-click to center'
    } catch (error) {
      if (!disposed && !abort.signal.aborted) { status.textContent = `${error.message}. Retrying…`; retryAt = Date.now() + 1000 }
    } finally { if (flight === abort) flight = null; if (!disposed) timeline.setBuffering(shown < (latest?.sequence ?? -1), latest?.timeline) }
  }
  const frameRuntime = viewer.runtime?.addFrameCallback ? viewer.runtime : null
  frameRuntime?.addFrameCallback(animate)
  const timer = repeat(() => { if (!frameRuntime) animate(); void tick() }, 33)
  return { receive(value) {
    const frame = value.liveFrame
    if (value.revision !== revision || frame?.revision !== revision || !Number.isSafeInteger(frame.sequence) || frame.sequence < 1 ||
      !Number.isSafeInteger(frame.bytes) || frame.bytes < 1 || !/^[a-f0-9]{64}$/.test(frame.sha256) || frame.sequence <= (latest?.sequence ?? -1)) return
    try { liveTimeline(frame.timeline) } catch { return }
    if (!frame.timeline?.playing) {
      flight?.abort(); flight = null; retryAt = 0
      pending = null; if (displayed) exact(displayed)
    }
    latest = frame; timeline.setBuffering(true, frame.timeline); void tick()
  }, dispose() { disposed = true; flight?.abort(); cancel(timer); frameRuntime?.removeFrameCallback(animate); apply?.clearInterpolation(); displayed = pending = segment = null; status.remove(); smoothLabel.remove(); timeline.dispose() } }
}
