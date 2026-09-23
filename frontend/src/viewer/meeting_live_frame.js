import { createClipApplier, gzipFrame, FRAME_LIMIT } from './trajectory_clip.js'

/** Coalesce slow connections to the newest absolute frame; never queue a movie. */
export function mountMeetingLiveFrame({ viewer, base, revision, fetch: request = fetch, document: doc = document,
  setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  const current = viewer.current, status = doc.createElement('span')
  status.dataset.liveFrameStatus = ''; status.setAttribute('role', 'status')
  doc.body.insertBefore(status, doc.querySelector('main'))
  let latest = null, shown = -1, flight = null, disposed = false, apply = null, retryAt = 0
  async function tick() {
    if (disposed || flight || !latest || latest.sequence <= shown || viewer.current !== current || Date.now() < retryAt) return
    const frame = latest, abort = new AbortController(); flight = abort
    const timeout = setTimeout(() => abort.abort(), 15000)
    try {
      const response = await request(`${base}/live-frame?revision=${revision}&sequence=${frame.sequence}`, { signal: abort.signal })
      if (response.status === 409) return
      if (!response.ok) throw new Error('Trajectory connection interrupted')
      const delivered = response.headers.get('X-NADOC-Sequence')
        ? { sequence: Number(response.headers.get('X-NADOC-Sequence')), bytes: Number(response.headers.get('Content-Length')), sha256: response.headers.get('X-NADOC-SHA256') } : frame
      if (!Number.isSafeInteger(delivered.sequence) || delivered.sequence < frame.sequence || !Number.isSafeInteger(delivered.bytes) || delivered.bytes < 1 || delivered.bytes > FRAME_LIMIT || !/^[a-f0-9]{64}$/.test(delivered.sha256)) throw new Error('Invalid streamed frame header')
      if (Number(response.headers.get('Content-Length')) !== delivered.bytes) throw new Error('Invalid streamed frame length')
      const buffer = await response.arrayBuffer()
      if (buffer.byteLength !== delivered.bytes) throw new Error('Incomplete streamed frame')
      const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(b => b.toString(16).padStart(2, '0')).join('')
      if (digest !== delivered.sha256) throw new Error('Streamed frame identity mismatch')
      const raw = await gzipFrame(buffer, true)
      if (disposed || viewer.current !== current) return
      apply ??= createClipApplier(current)
      apply.apply(raw); shown = delivered.sequence; status.textContent = ''
      const viewStatus = doc.getElementById('status')
      if (viewStatus) viewStatus.textContent = 'Shared visualization · Orbit, pan and zoom · Double-click to center'
    } catch (error) {
      if (!disposed) { status.textContent = `${error.message}. Retrying…`; retryAt = Date.now() + 1000 }
    } finally { clearTimeout(timeout); flight = null }
  }
  const timer = repeat(tick, 125)
  return { receive(value) {
    const frame = value.liveFrame
    if (value.revision !== revision || frame?.revision !== revision || !Number.isSafeInteger(frame.sequence) || frame.sequence < 1 ||
      !Number.isSafeInteger(frame.bytes) || frame.bytes < 1 || frame.bytes > FRAME_LIMIT || !/^[a-f0-9]{64}$/.test(frame.sha256) || frame.sequence <= (latest?.sequence ?? -1)) return
    latest = frame; void tick()
  }, dispose() { disposed = true; flight?.abort(); cancel(timer); status.remove() } }
}
