import './sharing_controls.css'
import { decodeContainer } from './package_container.js'
import { gzipFrame } from './trajectory_clip.js'
import { createLiveFrameCapture, liveSceneSignature } from './live_frame_capture.js'
import { visualizationProgress } from './visualization_progress.js'
import { broadcastDocument } from './broadcast_fingerprint.js'

const sameJob = (a, b) => !!a?.id && a.id === b?.id && a.engine === b?.engine
const prefix = engine => engine === 'namd' ? 'md' : 'oxdna'
const equal = (a, b) => a && a.length === b.length && a.every((v, i) => v === b[i])

/** A publication belongs to a job, independently of the editor's selection. */
export function initJobSharing({ prepared, store, getSelection, getSource, showNative, getRoom, beforeStart = async () => {}, onSharedChange = async () => {}, perspective = true,
  document: doc = document, fetch: request = fetch, setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  let shared = null, lease = '', room = null, revision = '', capture = null, busy = false, disposed = false
  let lastFrame = null, sentCamera = '', held = false, heartbeat = 0, epoch = 0, identity = null, switching = false, flight = null
  let pendingJob = null, progressFlight = null, sentProgress = 'null'
  const status = doc.createElement('p'); status.className = 'sharing-job-status'; status.setAttribute('role', 'status')
  const buttons = new Map()
  for (const engine of ['oxdna', 'namd']) {
    const header = doc.getElementById(`${prefix(engine)}-jobs-viz-toggle`)
    if (!header) continue
    const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn sharing-job-toggle'
    button.dataset.shareJob = engine; button.hidden = true
    button.onclick = event => { event.stopPropagation(); void toggle(engine) }
    header.append(button); buttons.set(engine, button)
  }
  function message(text) { status.textContent = text }
  const selection = () => getSelection() ?? {}
  function paint() {
    const selected = selection(), available = getRoom()
    for (const [engine, button] of buttons) {
      const active = shared?.engine === engine && sameJob(shared, selected)
      button.hidden = !available
      button.textContent = active ? 'Stop sharing' : 'Share'
      button.dataset.sharing = String(active); button.setAttribute('aria-pressed', String(active))
      button.disabled = switching || !selected.id || selected.engine !== engine
      button.title = active ? 'Return guests to the native NADOC model' : 'Share this job using the current presentation link'
    }
    const parent = buttons.get(selected.engine)?.parentElement?.parentElement
    if (parent && status.parentElement !== parent) parent.append(status)
    for (const row of doc.querySelectorAll('[data-job-id]')) {
      const active = !!shared && row.dataset.jobId === shared.id
      const dot = row.querySelector('[data-job-sharing-dot]')
      if (active && !dot) {
        const marker = doc.createElement('span'); marker.dataset.jobSharingDot = ''; marker.className = 'sharing-job-dot'
        marker.title = 'currently sharing this job for presentation'; marker.setAttribute('aria-label', marker.title)
        row.append(marker)
      } else if (!active && dot) dot.remove()
    }
    const broadcast = doc.getElementById('menu-help-broadcast')
    if (broadcast) broadcast.disabled = !!shared || switching
  }
  async function api(action, body, token = lease) {
    const response = await request(`/__nadoc_share/shares/${room}/broadcast/${action}`, { method: 'POST',
      headers: { 'X-NADOC-Share': '1', 'X-NADOC-Broadcast': token }, body })
    const value = await response.json()
    if (!response.ok) throw new Error(value.error || 'Job sharing connection failed')
    return value
  }
  const current = (job, ticket) => !disposed && ticket === epoch && sameJob(job, selection()) && identity === broadcastDocument(store.getState())
  function ready(job) {
    const source = getSource?.(job.engine), off = doc.getElementById(`${prefix(job.engine)}-jobs-viz-off`)
    if (!off?.checked && source?.controller?.activeJobId() && source.controller.activeJobId() !== job.id) throw new Error('Waiting for the selected job visualization to finish loading.')
    return source
  }
  async function publish(job, ticket) {
    ready(job)
    const source = prepared.captureView(false)
    if (capture && liveSceneSignature(source) === capture.signature && await publishFrame(source, job, ticket)) return true
    const result = await prepared.exportView({ presentation: false })
    if (result?.requiresWideLineViewer && !getRoom()?.capabilities?.includes('guest-visualizations-v1')) throw new Error('Restart presentation hosting after the current meeting to enable nanopore ion paths.')
    if (!result) throw new Error('Another view export is in progress. Please retry.')
    if (!current(job, ticket)) return false
    const next = createLiveFrameCapture(decodeContainer(result.buffer), prepared.captureView(false))
    const updated = await api('scene', result.buffer)
    if (disposed || ticket !== epoch) return false
    revision = updated.revision; capture = next; lastFrame = null; sentCamera = ''
    return true
  }
  async function publishFrame(source, job, ticket) {
    const frame = capture.frame(source)
    if (!frame) return false
    const bytes = new Uint8Array(frame)
    if (!equal(lastFrame, bytes)) {
      const compressed = await gzipFrame(frame)
      if (!current(job, ticket)) return false
      const packet = new Uint8Array(64 + compressed.byteLength)
      packet.set(new TextEncoder().encode(revision)); packet.set(new Uint8Array(compressed), 64)
      await api('frame', packet); lastFrame = bytes
    }
    // A successful upload is the publication boundary, even if the presenter
    // selected another job while the server was accepting this packet.
    return !disposed && ticket === epoch
  }
  async function toggle(engine) {
    if (switching || disposed) return
    const job = { ...selection() }
    if (!job.id || job.engine !== engine || !getRoom()) return
    switching = true; const ticket = ++epoch; paint()
    await flight
    busy = true
    try {
      if (sameJob(shared, job)) {
        // Use the existing native-position action, including each engine's overlay cleanup.
        doc.getElementById(`${prefix(engine)}-jobs-viz-off`)?.click()
        await showNative?.()
        if (!current(job, ticket)) throw new Error('Selection changed. Select the shared job to stop sharing.')
        if (!await publish(job, ticket)) return
        await api('pause'); lease = ''; shared = null; capture = null
        message('Guests are viewing the native NADOC model. The invitation remains open.')
      } else {
        const target = getRoom()
        if (!target.capabilities?.includes('job-stream-v1')) throw new Error('This sharing host needs the job-stream update. End this meeting and restart hosting to enable job sharing.')
        identity = broadcastDocument(store.getState())
        ready(job)
        await beforeStart()
        pendingJob = job
        if (!current(job, ticket)) return
        if (!lease) {
          room = target.id
          const started = await api('start', JSON.stringify({ jobStream: true }), '')
          lease = started.lease; revision = started.revision
        }
        if (await publish(job, ticket)) {
          shared = job; held = false; sentProgress = ''
          message(`Sharing ${engine === 'namd' ? 'NAMD' : 'oxDNA'} job ${job.id}. Visualization changes and playback are live.`)
        }
      }
    } catch (error) { message(error.message) }
    finally {
      if (!shared && lease) { await api('pause').catch(() => {}); lease = '' }
      pendingJob = null; busy = false; switching = false; paint()
      await onSharedChange(shared)
    }
  }
  async function runTick() {
    if (disposed) return
    paint()
    if (busy || switching || !shared || !lease) return
    if (getRoom()?.id !== room) { epoch++; shared = null; lease = ''; capture = null; paint(); return }
    busy = true; const ticket = epoch, job = shared
    try {
      if (Date.now() - heartbeat > 4000) { await api('heartbeat'); heartbeat = Date.now() }
      if (!current(job, ticket)) {
        if (!held) { await api('hold'); held = true; sentCamera = '' }
        message(`Job ${job.id} remains shared, paused on its last frame. Your selected job is private.`)
        return
      }
      if (visualizationProgress(doc, job.engine)) return
      ready(job)
      const source = prepared.captureView(false)
      if (!capture || liveSceneSignature(source) !== capture.signature) {
        await publish(job, ticket)
      } else {
        if (!await publishFrame(source, job, ticket)) return
      }
      if (!current(job, ticket)) return
      const view = prepared.captureView(false), camera = { ...view.pose, near: view.camera.near, far: view.camera.far }
      const encoded = JSON.stringify(camera)
      if (perspective && sentCamera !== encoded) { await api('camera', JSON.stringify({ revision, camera })); sentCamera = encoded }
      held = false; message(`Sharing job ${job.id}. Guests can explore independently or follow your perspective.`)
    } catch (error) { message(`${error.message} Guests keep the last shared frame.`) }
    finally { busy = false; paint() }
  }
  async function reportProgress() {
    const job = pendingJob ?? shared
    if (!lease || !getRoom()?.capabilities?.includes('guest-visualizations-v1')) return
    const value = sameJob(job, selection()) && identity === broadcastDocument(store.getState()) ? visualizationProgress(doc, job.engine) : null
    const encoded = JSON.stringify(value)
    if (encoded !== sentProgress) { await api('progress', encoded); sentProgress = encoded }
  }
  function tick() {
    if (!disposed && !progressFlight) progressFlight = reportProgress().catch(() => {}).finally(() => { progressFlight = null })
    if (!flight) flight = runTick().finally(() => { flight = null })
    return flight
  }
  const timer = repeat(tick, 125)
  paint()
  return { tick, toggle, async setPerspective(value) {
    perspective = value; sentCamera = ''
    await flight
    if (!value && lease) await api('hold')
    if (value) await tick()
  }, get active() { return !!shared }, get shared() { return shared && { ...shared } }, refresh: paint,
    dispose() {
      disposed = true; epoch++; cancel(timer)
      if (lease) void api('pause').catch(() => {})
      shared = null; busy = false; paint()
      for (const button of buttons.values()) button.remove()
      status.remove()
    } }
}
