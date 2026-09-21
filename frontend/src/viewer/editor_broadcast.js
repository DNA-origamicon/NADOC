import './sharing_controls.css'
import { broadcastDocument, broadcastFingerprint } from './broadcast_fingerprint.js'

/** Temporary editor presenter controls. No scene export runs inside the render loop. */
export function initEditorBroadcast({ prepared, store, document: doc = document, fetch: request = fetch,
  setInterval: repeat = setInterval, clearInterval: cancel = clearInterval, now = () => performance.now(), log = console.info }) {
  const trigger = doc.getElementById('menu-help-broadcast')
  const dialog = doc.createElement('dialog'); dialog.id = 'editor-broadcast-dialog'
  dialog.className = 'sharing-dialog sharing-dialog--broadcast'
  dialog.setAttribute('aria-labelledby', 'broadcast-title')
  dialog.innerHTML = `<header class="sharing-header"><h2 id="broadcast-title">Broadcast to presentation</h2><button class="btn" data-close>Close</button></header><p class="sharing-description">Choose an existing share link. Guests can explore independently or choose Jump and Follow.</p>
    <label class="sharing-field">Presentation<select class="select" data-room aria-label="Presentation"></select></label>
    <div class="sharing-card"><label class="sharing-check"><input type="checkbox" data-camera checked>Share my perspective</label><label class="sharing-check"><input type="checkbox" data-visuals checked>Share current visualizations</label><p class="sharing-description">Visualizations update after changes settle. Multi-view broadcasts the last pane you used. Changing files or opening an unsupported view stops broadcasting; guests keep the last shared scene.</p></div>
    <div class="sharing-actions"><button class="btn btn--primary" data-start disabled>Start broadcasting</button></div><p class="sharing-status" data-status role="status" aria-live="polite"></p>`
  const badge = doc.createElement('div'); badge.id = 'editor-broadcast-status'; badge.hidden = true
  badge.className = 'sharing-badge'
  const label = doc.createElement('span'), stopButton = doc.createElement('button'); stopButton.textContent = 'Stop broadcast'; stopButton.className = 'btn btn--danger'; badge.append(label, stopButton)
  doc.body.append(dialog, badge)
  const el = key => dialog.querySelector(`[data-${key}]`), host = doc.defaultView
  let active = false, starting = false, startPending = false, disposed = false, inFlight = false, generation = 0, room = null, lease = '', revision = '', identity = null
  let cameraOn = true, visualsOn = true, sentCamera = '', sentVisual = '', candidate = '', candidateSince = 0, checkedAt = -Infinity, exportedAt = -Infinity, heartbeatAt = 0
  let title = '', dragging = false, gestureAt = -Infinity
  function message(value) { el('status').textContent = value; label.textContent = value }
  function paint() { trigger?.setAttribute('aria-pressed', String(active)); if (trigger) trigger.textContent = active ? '✓ Broadcast to presentation' : 'Broadcast to presentation…'; stopButton.textContent = active || starting ? 'Stop broadcast' : 'Dismiss' }
  async function api(path, options = {}) {
    const response = await request(`/__nadoc_share/${path}`, { ...options, headers: { 'X-NADOC-Share': '1', ...options.headers } })
    const value = await response.json(); if (!response.ok) throw new Error(value.error || 'Presentation connection failed')
    return value
  }
  const send = (action, body, token = lease, id = room) => api(`shares/${id}/broadcast/${action}`, { method: 'POST', headers: { 'X-NADOC-Broadcast': token }, body, keepalive: action === 'pause' })
  function stop(reason = 'Broadcast paused. Guests keep the last shared view.') {
    generation++; active = false; starting = false
    const previous = lease; lease = ''
    if (previous) void send('pause', undefined, previous).catch(() => {})
    badge.hidden = false; message(reason); paint()
  }
  function sameDocument() { return broadcastDocument(store.getState()) === identity }
  async function publishVisual(ticket, signature) {
    const started = now(), result = await prepared.exportView({ presentation: true })
    if (!result) throw new Error('Another export is busy; stop and retry broadcasting.')
    if (!active || ticket !== generation || !sameDocument()) return
    message(`Updating shared visualizations · ${title}`)
    const updated = await send('scene', result.buffer)
    if (!active || ticket !== generation) return
    revision = updated.revision; sentCamera = ''; sentVisual = signature; exportedAt = now()
    log('[NADOC_PRESENTATION_UPDATE v1] ' + JSON.stringify({ schema: 1, room, bytes: result.buffer.byteLength, elapsed_ms: now() - started, revision }))
  }
  async function tick() {
    if (!active || inFlight || disposed) return
    if (!sameDocument()) { stop('Broadcast stopped because the open file changed.'); return }
    inFlight = true; const ticket = generation
    try {
      const source = prepared.captureView()
      if (visualsOn && now() - checkedAt >= 1000 && !dragging && now() - gestureAt > 400) {
        checkedAt = now()
        const signature = broadcastFingerprint(source)
        if (signature !== candidate) { candidate = signature; candidateSince = now() }
        if (signature !== sentVisual && now() - candidateSince >= 600 && now() - exportedAt >= 3000) await publishVisual(ticket, signature)
      }
      if (!active || ticket !== generation) return
      if (cameraOn) {
        const current = prepared.captureView(), pose = { ...current.pose, near: current.camera.near, far: current.camera.far }, encoded = JSON.stringify(pose)
        if (encoded !== sentCamera) { await send('camera', JSON.stringify({ revision, camera: pose })); sentCamera = encoded; heartbeatAt = now() }
      }
      if (now() - heartbeatAt > 4000) { await send('heartbeat'); heartbeatAt = now() }
      if (active && ticket === generation) message(`Broadcasting ${cameraOn && visualsOn ? 'perspective + visualizations' : cameraOn ? 'perspective' : 'visualizations'} · ${title}`)
    } catch (error) {
      if (active && ticket === generation) {
        if (error.code === 'VIEW_NOT_READY') {
          message(error.message)
          try { if (now() - heartbeatAt > 4000) { await send('heartbeat'); heartbeatAt = now() } } catch (reason) { stop(reason.message) }
        } else stop(error.message)
      }
    }
    finally { inFlight = false }
  }
  async function start() {
    if (starting || active || disposed) return
    if (inFlight || startPending) { message('Waiting for the previous update to finish. Please retry in a moment.'); return }
    cameraOn = el('camera').checked; visualsOn = el('visuals').checked
    if (!cameraOn && !visualsOn) { message('Choose perspective, visualizations, or both.'); return }
    identity = broadcastDocument(store.getState())
    if (!identity) { message('Open a design before broadcasting.'); return }
    starting = true; startPending = true; const ticket = ++generation; room = el('room').value
    const startRoom = room
    title = el('room').selectedOptions[0]?.textContent ?? 'Presentation'; el('start').disabled = true
    try {
      prepared.captureView() // Reject unsupported host modes before acquiring authority.
      const options = visualsOn ? {} : { cameraOnly: true, sourceHash: await prepared.sourceHash() }
      if (ticket !== generation || disposed || !sameDocument()) return
      const result = await send('start', JSON.stringify(options), '')
      if (ticket !== generation || disposed || !sameDocument()) { await send('pause', undefined, result.lease, startRoom); return }
      lease = result.lease; revision = result.revision; active = true; starting = false
      sentCamera = ''; sentVisual = ''; candidate = ''; checkedAt = -Infinity; exportedAt = -Infinity; heartbeatAt = now()
      badge.hidden = false; dialog.close(); paint()
      if (visualsOn) {
        inFlight = true
        try { await publishVisual(ticket, broadcastFingerprint(prepared.captureView())) } finally { inFlight = false }
      }
      await tick()
    } catch (error) { if (ticket === generation) { stop(error.message); message(error.message) } }
    finally { starting = false; startPending = false; el('start').disabled = false }
  }
  async function show() {
    if (active || starting) { stop(); return }
    dialog.showModal(); el('start').disabled = true; message('Looking for active share links…')
    try {
      const value = await api('status'); if (disposed) return
      el('room').replaceChildren(...(value.shares ?? []).map(share => { const option = doc.createElement('option'); option.value = share.id; option.textContent = share.title; return option }))
      if (!value.capabilities?.includes('editor-broadcast-v1')) throw new Error(value.running ? 'This host was started before editor broadcasting was installed. After your current meeting, stop hosting and create a new share link to use this feature.' : 'Create a link with Help → Share link first.')
      if (!value.shares.length) throw new Error('Create a link with Help → Share link first.')
      el('start').disabled = false; message('Broadcasting is off. Guests will keep the same link and sign-in.')
    } catch (error) { message(error.message) }
  }
  const changed = () => { if (active || starting) stop('Broadcast stopped because the open file changed.') }
  const unsubscribe = store.subscribe(() => { if ((active || starting) && !sameDocument()) changed() })
  const pointerDown = event => { if (event.target.closest?.('canvas, .mv-viewport-panel')) { dragging = true; gestureAt = now() } }
  const pointerUp = () => { dragging = false; gestureAt = now() }
  const wheel = event => { if (event.target.closest?.('canvas, .mv-viewport-panel')) gestureAt = now() }
  const offline = () => { if (active || starting) stop('Connection lost. Broadcast is off; start it again when connected.') }
  trigger?.addEventListener('click', show); el('start').onclick = start; el('close').onclick = () => dialog.close(); stopButton.onclick = () => { if (active || starting) stop(); else badge.hidden = true }
  doc.addEventListener('pointerdown', pointerDown, true); doc.addEventListener('pointerup', pointerUp, true); doc.addEventListener('wheel', wheel, { capture: true, passive: true })
  host?.addEventListener('nadoc:workspace-path-change', changed); host?.addEventListener('nadoc:document-reset', changed)
  host?.addEventListener('offline', offline); host?.addEventListener('pagehide', offline)
  const timer = repeat(tick, 250); paint()
  return { show, start, stop, tick, get active() { return active }, dispose() {
    if (disposed) return
    stop(); disposed = true; cancel(timer); unsubscribe?.(); trigger?.removeEventListener('click', show)
    doc.removeEventListener('pointerdown', pointerDown, true); doc.removeEventListener('pointerup', pointerUp, true); doc.removeEventListener('wheel', wheel, true)
    host?.removeEventListener('nadoc:workspace-path-change', changed); host?.removeEventListener('nadoc:document-reset', changed); host?.removeEventListener('offline', offline); host?.removeEventListener('pagehide', offline)
    dialog.remove(); badge.remove()
  } }
}
