import { createClipApplier, gzipFrame, clipFrameAt, validateClip, FRAME_LIMIT } from './trajectory_clip.js'

/** Independent bounded receiver: one download in flight, absolute frames, shared clock. */
export function mountMeetingTrajectory({ viewer, base, role, document: doc = document, fetch: request = fetch,
  now = () => performance.now(), setInterval: repeat = setInterval, clearInterval: cancel = clearInterval, log = console.info }) {
  const current = viewer.current, clip = current?.data?.trajectory
  if (!clip) return { receive() {}, dispose() {} }
  validateClip(clip)
  const apply = createClipApplier(current), cache = new Map(), bar = doc.createElement('div')
  bar.dataset.trajectory = ''; bar.style.cssText = 'display:flex;gap:12px;padding:8px 18px;align-items:center;flex-wrap:wrap'
  bar.innerHTML = `<strong>Recorded trajectory</strong>${role === 'presenter' ? '<button data-play>Play</button><input data-seek type="range" min="0" value="0" aria-label="Shared trajectory frame"><select data-speed aria-label="Trajectory frames per second"><option>4</option><option>8</option><option>15</option><option>30</option></select>' : ''}<button data-preload>Buffer clip</button><span data-progress role="status"></span><button data-metrics>Copy trajectory metrics</button>`
  doc.body.insertBefore(bar, doc.querySelector('main'))
  const el = key => bar.querySelector(`[data-${key}]`), status = el('progress')
  let state = null, anchor = 0, serverAt = 0, disposed = false, flight = null, epoch = 0, bytes = 0, shown = -1, fetchMs = 150, lastTick = now(), lastReport = now(), preload = false, retryAt = 0, syncAt = now() + 5000, syncing = false, networkDelay = 0, sequence = -1
  const startedAt = now(), clockAbort = new AbortController()
  const metrics = { schema: 1, clip: clip.id, downloaded_bytes: 0, applied_frames: 0, skipped_frames: 0, waiting_ms: 0, errors: 0, peak_cache_bytes: 0, max_apply_ms: 0, last_fetch_ms: null, temporal_step: 1 }
  const currentTime = () => serverAt + now() - anchor
  const target = () => state ? clipFrameAt(state, currentTime(), clip.frames.length) : 0
  function report() { const elapsed = now() - startedAt; const value = { ...metrics, elapsed_ms: elapsed, applied_samples_per_second: elapsed > 0 ? metrics.applied_frames * 1000 / elapsed : 0, measurement: 'trajectory sample application; not render FPS', clock_rtt_ms: networkDelay * 2, displayed_source_frame: clip.sourceFrames[shown] ?? null, target_source_frame: clip.sourceFrames[target()], cache_bytes: bytes, sample_lag_seconds: shown < 0 ? null : Math.max(0, target() - shown) / (state?.fps ?? clip.fps) }; log('[NADOC_TRAJECTORY_PERF v1] ' + JSON.stringify(value)); return value }
  function resetRequest() { epoch++; flight?.abort.abort(); flight = null }
  async function download(index) {
    const ticket = epoch, abort = new AbortController(), started = now(), record = { index, abort }; flight = record
    const timeout = setTimeout(() => abort.abort(), state?.playing ? 30000 : 120000)
    try {
      const response = await request(`${base}/frame?clip=${clip.id}&index=${index}`, { signal: abort.signal })
      if (!response.ok) throw new Error('Trajectory transfer failed')
      const expected = clip.frames[index]
      if (!expected || expected.bytes > FRAME_LIMIT || Number(response.headers.get('Content-Length')) !== expected.bytes) throw new Error('Invalid trajectory frame length')
      const buffer = await response.arrayBuffer()
      if (buffer.byteLength !== expected.bytes) throw new Error('Incomplete trajectory frame')
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(b => b.toString(16).padStart(2, '0')).join('')
      if (hash !== expected.sha256) throw new Error('Trajectory frame identity mismatch')
      const raw = await gzipFrame(buffer, true)
      if (disposed || ticket !== epoch || current !== viewer.current) return
      fetchMs = Math.max(25, now() - started); metrics.last_fetch_ms = fetchMs
      metrics.downloaded_bytes += buffer.byteLength
      cache.set(index, raw); bytes += raw.byteLength
      while (bytes > 32 * 1024 * 1024 && cache.size > 1) { const key = cache.keys().next().value; bytes -= cache.get(key).byteLength; cache.delete(key); preload = false }
      metrics.peak_cache_bytes = Math.max(metrics.peak_cache_bytes, bytes)
    } catch (error) {
      if (!disposed && ticket === epoch) { metrics.errors++; retryAt = now() + 1000; status.textContent = `${error.message}. Retrying at the meeting time…` }
    } finally { clearTimeout(timeout); if (flight === record) flight = null }
  }
  async function command(frame, playing) {
    const response = await request(`${base}/trajectory`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: clip.id, frame, playing, fps: Number(el('speed').value) }) })
    if (!response.ok) throw new Error((await response.json()).error || 'Could not control trajectory')
    receive(await response.json())
  }
  function receive(value) {
    if (Number.isSafeInteger(value.sequence) && value.sequence < sequence) return
    if (Number.isSafeInteger(value.sequence)) sequence = value.sequence
    const next = value.trajectory
    if (!next || next.id !== clip.id || !Number.isFinite(value.serverTime)) return
    const changed = !state || next.at !== state.at || next.frame !== state.frame || next.playing !== state.playing || next.fps !== state.fps
    if (changed) { resetRequest(); preload = false; shown = -1 }
    state = next; serverAt = value.serverTime + networkDelay; anchor = now()
    if (el('play')) { el('play').textContent = next.playing ? 'Pause' : 'Play'; el('speed').value = String(next.fps) }
    tick()
  }
  async function syncClock() {
    syncing = true
    const started = now(), abort = new AbortController(), stop = () => abort.abort()
    clockAbort.signal.addEventListener('abort', stop, { once: true })
    const timeout = setTimeout(stop, 5000)
    try {
      const response = await request(`${base}/status`, { signal: abort.signal })
      if (!response.ok) return
      const value = await response.json()
      if (!disposed && !abort.signal.aborted) {
        networkDelay = Math.max(0, now() - started) / 2
        receive(value.presentation)
      }
    } catch { /* The event channel owns connection status; retry clock calibration later. */ }
    finally { clearTimeout(timeout); clockAbort.signal.removeEventListener('abort', stop); syncing = false; syncAt = now() + 10000 }
  }
  function tick() {
    if (disposed || viewer.current !== current || doc.hidden || !state || viewer.performanceApi.busy) return
    const index = target(), time = now()
    if (time >= syncAt && !syncing) void syncClock()
    // Never drain a historical queue. Choose the newest already-received frame at this meeting time.
    const available = state.playing ? [...cache.keys()].filter(i => i <= index).sort((a, b) => b - a)[0] : cache.has(index) ? index : undefined
    if (available !== undefined && available !== shown) {
      try { const started = now(); apply.apply(cache.get(available)); metrics.max_apply_ms = Math.max(metrics.max_apply_ms, now() - started); if (shown >= 0) metrics.skipped_frames += Math.max(0, available - shown - 1); shown = available; metrics.applied_frames++ }
      catch (error) { status.textContent = error.message; resetRequest(); disposed = true; return }
    }
    const waiting = shown !== index
    if (waiting && time - lastTick > 0) metrics.waiting_ms += Math.min(250, time - lastTick)
    lastTick = time
    const lag = shown < 0 ? null : Math.max(0, index - shown) / state.fps
    status.textContent = `${state.playing ? 'Playing' : 'Paused'} · source frame ${shown < 0 ? 'loading' : clip.sourceFrames[shown] + 1} / ${clip.sourceFrames.at(-1) + 1} · ${cache.size}/${clip.frames.length} buffered${lag > 1 ? ' · catching up' : ''} · exact Full samples`
    if (el('seek')) el('seek').value = String(index)
    el('preload').textContent = preload ? 'Buffering…' : cache.size === clip.frames.length ? 'Clip buffered' : 'Buffer clip'
    if (flight || time < retryAt) return
    let wanted
    if (!state.playing) wanted = !cache.has(index) ? index : preload ? clip.frames.findIndex((_, i) => !cache.has(i)) : -1
    else {
      const step = Math.max(1, Math.ceil(fetchMs * state.fps / 650)); metrics.temporal_step = step
      const lead = Math.min(clip.frames.length - 1, index + step)
      wanted = cache.has(lead) ? Math.min(clip.frames.length - 1, lead + step) : lead
      if (!cache.has(index) && shown < 0) wanted = index
    }
    if (wanted >= 0 && !cache.has(wanted)) void download(wanted)
    if (time - lastReport > 10000) { report(); lastReport = time }
  }
  if (el('seek')) { el('seek').max = String(clip.frames.length - 1); el('speed').value = String(clip.fps) }
  const invoke = (frame, playing) => command(frame, playing).catch(error => { status.textContent = error.message })
  if (el('play')) el('play').onclick = () => invoke(target() >= clip.frames.length - 1 ? 0 : target(), !state?.playing)
  if (el('seek')) el('seek').onchange = () => invoke(Number(el('seek').value), false)
  if (el('speed')) el('speed').onchange = () => invoke(target(), !!state?.playing)
  el('preload').onclick = () => { preload = true; tick() }
  el('metrics').onclick = async () => { const value = '[NADOC_TRAJECTORY_PERF v1] ' + JSON.stringify(report()); try { await doc.defaultView.navigator.clipboard.writeText(value) } catch { status.textContent = value } }
  const visibility = () => { if (doc.hidden) resetRequest(); else { syncAt = now(); tick() } }
  doc.addEventListener('visibilitychange', visibility)
  const timer = repeat(tick, 33)
  return { receive, dispose() { disposed = true; clockAbort.abort(); resetRequest(); cancel(timer); doc.removeEventListener('visibilitychange', visibility); cache.clear(); bar.remove(); report() } }
}
