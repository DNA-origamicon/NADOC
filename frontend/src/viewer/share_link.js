import { initEditorDrawings } from './editor_drawings.js'
import { initAnimationSharing } from './animation_sharing.js'
import { initMeetingTarget } from './meeting_target_ui.js'
import { initVRAvatarPublisher } from './vr_avatar_publisher.js'
import { broadcastDocument } from './broadcast_fingerprint.js'
import { waitForPublicHosting, publicHostingMessage } from './hosting_setup.js'
import { requireSharingCapabilities } from './sharing_capabilities.js'
import { initNativeViewToolSharing } from './native_view_tool_sharing.js'
import './sharing_controls.css'
import { icon } from '../ui/primitives/icon.js'
/** Editor-side share UI. Publishes a prepared snapshot through the local host. */
import { initEditorBroadcast } from './editor_broadcast.js'
import { initJobSharing } from './job_sharing.js'
import { initPresentationControls } from './presentation_controls.js'
export function initShareLink({ exportView, broadcast, document: doc = document, fetch: request = fetch, clipboard = navigator.clipboard }) {
  let preservingPerspective = false, nativeFlight = null, animationActive = false
  const presenter = broadcast ? initEditorBroadcast({ ...broadcast, document: doc, fetch: request, embedded: true, onStop: reason => {
    if (!preservingPerspective) { const wasSharing = controls.perspective; controls.setPerspective(false); if (wasSharing) controls.error(reason) }
  } }) : null
  const oldBroadcast = doc.getElementById('menu-help-broadcast')
  if (oldBroadcast) oldBroadcast.hidden = true
  const trigger = doc.getElementById('menu-file-sharing')
  const qrTrigger = doc.getElementById('menu-presentation-qr')
  const startTrigger = doc.getElementById('menu-presentation-start')
  const stopTrigger = doc.getElementById('menu-presentation-stop')
  const dialog = doc.createElement('dialog')
  dialog.id = 'share-link-dialog'
  dialog.className = 'sharing-dialog'
  dialog.setAttribute('aria-labelledby', 'share-link-title')
  dialog.innerHTML = `<header class="sharing-header"><h2 id="share-link-title">Sharing</h2><button class="btn" data-close aria-label="Close">×</button></header>
    <div class="sharing-actions" data-publish-actions><button class="btn btn--primary" data-create>Start presentation</button><button class="btn btn--danger" data-stop-host disabled>End presentation</button><button class="btn" data-reset-link hidden>Reset link</button></div>
    <div data-links class="sharing-actions sharing-links"></div>
    <progress data-preparation hidden aria-label="Preparing presentation"></progress>
    <p class="sharing-status" data-connection role="status" aria-live="polite"></p>
    <p class="sharing-status" data-status role="status" aria-live="polite"></p>
    <details class="sharing-error" data-error hidden><summary>Error log</summary><pre data-error-log></pre></details>`
  doc.body.append(dialog)
  const el = selector => dialog.querySelector(selector), status = el('[data-status]'), list = el('[data-links]')
  let hostingAbort = new AbortController(), documentEpoch = 0
  let polling = false, busy = false, refreshing = false, disposed = false, revision = 0, selectedId = null, shares = [], capabilities = [], jobs = null, statusTimer = null, jobOptions = null, hadSharedJob = false
  let invitation = null, invitationFlight = null
  const designKey = () => broadcast?.store ? broadcastDocument(broadcast.store.getState()) : null
  const designShares = value => (value.running === false ? [] : value.shares ?? []).filter(share => !broadcast?.store || share.key === designKey())
  const invitationCache = new Map()
  async function ensureInvitation(reset = false, background = false) {
    const key = designKey(), epoch = documentEpoch
    if (!key) return null
    if (!reset && invitationFlight?.key === key && invitationFlight.epoch === epoch && (background || !invitationFlight.background)) return invitationFlight.promise
    const promise = api('links', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key, reset, background }) }).then(value => {
      if (value.pending) return null
      if (!value.id || !value.url) throw new Error('Restart sharing hosting to enable persistent design links.')
      invitationCache.set(key, value)
      if (!disposed && epoch === documentEpoch && key === designKey()) { invitation = value; renderShares() }
      return value
    }).finally(() => { if (invitationFlight?.promise === promise) invitationFlight = null })
    invitationFlight = { key, epoch, background, promise }
    return promise
  }
  function prepareInvitation() {
    invitation = invitationCache.get(designKey()) ?? null
    renderShares()
    void ensureInvitation(false, true).catch(() => { /* Start or opening Sharing reports actionable setup errors. */ })
  }
  const currentRoom = () => shares.find(s => s.id === selectedId) ?? shares[0]
  const drawings = broadcast?.prepared ? initEditorDrawings({ prepared: broadcast.prepared, getRoom: () => capabilities.includes('guest-drawing-v1') ? currentRoom() : null, document: doc, fetch: request }) : null
  const currentInvitation = () => invitation ?? currentRoom()
  const meetingTarget = initMeetingTarget({ parent: dialog, document: doc, onError: reportError })
  async function stopNative() {
    preservingPerspective = true
    try { await presenter?.stop(); await nativeFlight?.catch(() => {}) } finally { preservingPerspective = false }
  }
  async function sharePerspective(enabled, refreshScene = false) {
    if (animationActive) return
    if (jobs?.active) return jobs.setPerspective(enabled)
    if (!enabled) return stopNative()
    const share = currentRoom()
    if (!share || !presenter) throw new Error('Create a presentation link in an open design first.')
    nativeFlight = presenter.present(share, { refreshScene })
    try { await nativeFlight } finally { nativeFlight = null }
  }
  const controls = initPresentationControls({ document: doc, onPerspective: sharePerspective, onEnd: stopHosting, onViewLock: async locked => {
    if (!capabilities.includes('view-lock-v1')) throw new Error('Restart presentation hosting to lock guest perspectives.')
    if (locked && !controls.perspective) {
      if (!jobs?.active) { nativeTools?.clear(); await nativeTools?.settle() }
      try { await sharePerspective(true, true); controls.setPerspective(true) }
      finally { if (!jobs?.active) { try { nativeTools?.remember() } catch { nativeTools?.clear() } } }
    }
    await api(`shares/${currentRoom().id}/broadcast/view-lock`, { method: 'POST', body: JSON.stringify({ locked }) })
  }, onGuestView: view => {
    try {
      broadcast?.prepared.viewSharedCamera(view.camera, { presentation: !jobs?.active, canMove: () => !!currentRoom() && (!jobs?.active || jobs.canViewShared) })
    } catch (error) { controls.error(error.message) }
  } })
  const nativeTools = broadcast?.prepared ? initNativeViewToolSharing({
    prepared: broadcast.prepared, store: broadcast.store, getRoom: currentRoom,
    getContext: () => ({ selection: jobOptions?.getSelection?.(),
      active: ['oxdna', 'namd'].map(engine => jobOptions?.getSource?.(engine)?.controller?.activeJobId?.() ?? null),
      modes: [...doc.querySelectorAll('input[id^="oxdna-jobs-viz-"], input[id^="md-jobs-viz-"]')].filter(input => input.checked).map(input => input.id) }),
    isBusy: () => busy || animationActive || !!jobs?.active,
    onError: message => controls.error(message),
    publish: async (result, current) => {
      if (!capabilities.includes('share-content-v1')) throw new Error('Restart presentation hosting after the current meeting to share view tool changes.')
      requireSharingCapabilities(result, capabilities)
      await stopNative()
      if (!current()) return false
      const id = currentRoom().id
      const share = await api(`shares/${id}/content`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-NADOC-Title': encodeURIComponent(result.title) }, body: result.buffer })
      if (disposed || !current()) return false
      shares = shares.map(value => value.id === id ? share : value)
      if (controls.perspective) await sharePerspective(true)
      return true
    },
  }) : null
  const animation = broadcast?.prepared ? initAnimationSharing({ prepared: broadcast.prepared, fetch: request,
    getRoom: () => { const room = currentRoom(); return room ? { ...room, capabilities } : null },
    onActive: active => { animationActive = active; controls.setAnimation(active) },
    onError: message => controls.error(message),
    beforeStart: async () => { nativeTools?.clear(); await nativeTools?.settle(); await stopNative(); await jobs?.suspend(); broadcast.prepared.cancelSharedCamera?.() },
    afterStop: async restore => {
      if (!currentRoom()) return
      if (restore && !disposed) {
        const room = currentRoom(), result = await broadcast.prepared.exportView({ presentation: false })
        if (result && room.id === currentRoom()?.id) {
          requireSharingCapabilities(result, capabilities)
          const updated = await api(`shares/${room.id}/content`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-NADOC-Title': encodeURIComponent(result.title) }, body: result.buffer })
          shares = shares.map(value => value.id === room.id ? updated : value)
        }
      }
      try { nativeTools?.remember() } catch { nativeTools?.clear() }
      if (controls.perspective) await sharePerspective(true)
    },
  }) : null
  const vrAvatar = initVRAvatarPublisher({ getRoom: currentRoom,
    available: () => !busy && !disposed && capabilities.includes('vr-avatar-v1'), request,
    publish: (room, body) => api(`shares/${room.id}/avatar`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) }),
    onError: message => controls.error(message),
  })
  function syncControls() {
    controls.setActive(shares.length > 0)
    controls.setParticipants(currentRoom()?.participants ?? [], { serverTime: currentRoom()?.serverTime })
    if (!shares.length) void stopNative()
    jobs?.refresh()
  }
  function clearError() {
    el('[data-error]').hidden = true
    el('[data-error]').open = false
    el('[data-error-log]').textContent = ''
  }
  function reportError(error) {
    status.textContent = ''
    const details = el('[data-error]')
    if (details.hidden) details.open = false
    details.hidden = false
    const log = el('[data-error-log]')
    log.textContent += `${log.textContent ? '\n\n' : ''}${error.message ?? error}`
  }
  function syncButtons() {
    meetingTarget.setBusy(false)
    el('[data-create]').disabled = busy || refreshing || shares.length > 0 || (!!broadcast?.store && !designKey())
    if (startTrigger) startTrigger.disabled = el('[data-create]').disabled
    el('[data-reset-link]').hidden = !invitation
    el('[data-reset-link]').disabled = busy || refreshing
    el('[data-preparation]').hidden = !busy
    el('[data-stop-host]').disabled = busy || refreshing || shares.length === 0
    if (stopTrigger) stopTrigger.disabled = el('[data-stop-host]').disabled
    if (qrTrigger) {
      const room = currentInvitation()
      qrTrigger.disabled = !room?.qrUrl || (Number.isFinite(room.expiresAt) && room.expiresAt <= Date.now())
      qrTrigger.title = room?.qrUrl ? 'Show the current passwordless guest invitation' : 'Open a design to prepare its passwordless QR code'
    }
    for (const copy of dialog.querySelectorAll('[data-copy-link], [data-copy-password]')) copy.disabled = false
  }
  async function stopHosting() {
    if (busy) return
    revision++; busy = true; clearError(); syncButtons()
    dialog.setAttribute('aria-busy', 'true')
    status.textContent = 'Stopping…'
    try {
      nativeTools?.clear()
      await nativeTools?.settle()
      broadcast?.prepared.cancelSharedCamera?.()
      await animation?.stop()
      await api('stop', { method: 'POST' })
      shares = []; selectedId = null; renderShares()
      status.textContent = ''
    } catch (error) { reportError(error); throw error }
    finally { busy = false; refreshing = false; dialog.setAttribute('aria-busy', 'false'); syncButtons() }
  }
  async function api(path, options = {}) {
    const response = await request(`/__nadoc_share/${path}`, { ...options, headers: { 'X-NADOC-Share': '1', ...options.headers } })
    const value = await response.json()
    if (!response.ok) throw new Error(value.error || 'Could not contact the local sharing host')
    return value
  }
  function renderShares() {
    meetingTarget.setShare(currentInvitation())
    selectedId = shares.some(share => share.id === selectedId) ? selectedId : shares[0]?.id ?? null
    if (!currentInvitation()) list.replaceChildren()
    for (const [key, label, value] of [
      ['link', 'Link', currentInvitation()?.url],
      ['password', 'Password', currentInvitation()?.password],
    ]) {
      let row = el(`[data-share-field="${key}"]`)
      if (!value) { row?.remove(); continue }
      if (!row) {
        row = doc.createElement('div')
        row.className = 'sharing-copy-field'; row.dataset.shareField = key
        const caption = doc.createElement('label')
        caption.textContent = label; caption.htmlFor = `share-${key}-value`
        const line = doc.createElement('div'); line.className = 'sharing-copy-row'
        const input = doc.createElement('input')
        input.type = 'text'; input.readOnly = true; input.spellcheck = false
        input.className = 'input'; input.id = caption.htmlFor; input.dataset[key] = ''
        input.addEventListener('dblclick', () => input.select())
        const copy = doc.createElement('button')
        copy.type = 'button'; copy.className = 'btn sharing-copy-button'
        copy.setAttribute(`data-copy-${key}`, '')
        copy.setAttribute('aria-label', `Copy ${key}`); copy.title = `Copy ${key}`
        copy.append(icon('copy', { size: 16 }))
        copy.onclick = async () => {
          clearError()
          try {
            await clipboard.writeText(input.value)
            status.textContent = `${label} copied`
          } catch (error) { reportError(new Error(`Could not copy ${key}: ${error.message ?? error}`)) }
        }
        line.append(input, copy); row.append(caption, line); list.append(row)
      }
      const input = row.querySelector('input')
      // Polling must not disturb a manual selection in an unchanged field.
      if (input.value !== value) input.value = value
    }
    syncButtons()
    syncControls()
  }
  function connectionStatus(value) {
    el('[data-connection]').textContent = value.publicAccess?.state === 'ready'
      ? 'Internet sharing ready' : publicHostingMessage(value.publicAccess)
  }
  async function refresh() {
    const ticket = ++revision
    refreshing = true; syncButtons()
    try {
      const value = await api('status')
      if (disposed || ticket !== revision) return
      shares = designShares(value)
      capabilities = value.capabilities ?? []
      connectionStatus(value)
      renderShares()
      if (value.updateRequired) reportError(new Error('End the presentation, then enable the link to load the updated viewer.'))

    } catch (error) { if (!disposed && ticket === revision) reportError(error) }
    finally { if (!disposed && ticket === revision) { refreshing = false; syncButtons() } }
  }
  async function create() {
    if (busy || refreshing || shares.length) return
    revision++; busy = true; clearError(); syncButtons()
    const epoch = documentEpoch
    hostingAbort = new AbortController()
    const current = () => !disposed && epoch === documentEpoch
    dialog.setAttribute('aria-busy', 'true')
    try {
      await nativeTools?.settle()
      const nativeContext = nativeTools?.capture()
      nativeTools?.clear()
      status.textContent = 'Preparing presentation…'
      const link = await ensureInvitation()
      if (!current()) return
      if (link) await api(`links/${link.id}/preparing`, { method: 'POST' })
      if (!current()) return
      const result = await exportView({ presentation: true })
      if (!current()) return
      if (!result) throw new Error('Another export is busy; please retry.')
      const host = await waitForPublicHosting({ api, signal: hostingAbort.signal, onProgress: message => { if (!disposed) status.textContent = message } })
      if (!current()) return
      connectionStatus(host)
      capabilities = host.capabilities ?? []
      // Another editor may have created a link while this dialog was connecting.
      if (designShares(host).length) {
        shares = designShares(host); renderShares(); status.textContent = ''; return
      }
      requireSharingCapabilities(result, capabilities)
      status.textContent = 'Starting presentation…'
      const share = await api('create', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-NADOC-Title': encodeURIComponent(result.title), ...(link ? { 'X-NADOC-Link': link.id } : {}) }, body: result.buffer })
      if (!current()) { await api(`shares/${share.id}`, { method: 'DELETE', keepalive: true }); return }
      if (!disposed) {
        shares = [share]; selectedId = share.id; renderShares()
        if (nativeContext) nativeTools.remember({ ...nativeContext, room: share.id })
        if (controls.perspective) await sharePerspective(true)
        status.textContent = ''
      }
    } catch (error) { if (current()) reportError(error) }
    finally {
      if (invitation && current()) void api(`links/${invitation.id}/preparing`, { method: 'DELETE' }).catch(() => {})
      busy = false; if (!disposed) { dialog.setAttribute('aria-busy', 'false'); syncButtons() }
    }
  }
  function documentClosed() {
    void animation?.stop().catch(() => {})
    documentEpoch++; revision++; refreshing = false
    hostingAbort.abort(new DOMException('Part session closed', 'AbortError'))
    nativeTools?.clear()
    if (invitation) void api(`links/${invitation.id}/preparing`, { method: 'DELETE', keepalive: true }).catch(() => {})
    const previous = shares; invitation = null; shares = []; selectedId = null; renderShares()
    status.textContent = ''
    for (const share of previous) void api(`shares/${share.id}`, { method: 'DELETE', keepalive: true }).catch(reportError)
  }
  const hostWindow = doc.defaultView
  hostWindow?.addEventListener('nadoc:document-reset', documentClosed)
  hostWindow?.addEventListener('pagehide', documentClosed)
  let identity = broadcast?.store ? broadcastDocument(broadcast.store.getState()) : null
  const unsubscribeDocument = broadcast?.store?.subscribe(() => {
    const next = broadcastDocument(broadcast.store.getState())
    if (next !== identity) { identity = next; documentClosed(); prepareInvitation() }
  })
  const show = () => {
    dialog.showModal()
    if (!busy) {
      void refresh()
      void ensureInvitation().catch(reportError)
    }
  }
  const startFromMenu = () => { if (!dialog.open) dialog.showModal(); void create() }
  const resetLink = async () => {
    if (busy || refreshing) return
    busy = true; revision++; clearError(); syncButtons()
    try {
      await ensureInvitation(true)
      shares = []; selectedId = null; renderShares()
      status.textContent = 'Link reset. Previous invitations no longer work.'
    } catch (error) { reportError(error) }
    finally { busy = false; syncButtons() }
  }
  const showQR = () => meetingTarget.showQR()
  const stopFromMenu = () => { void stopHosting().catch(error => controls.error(error.message)) }
  startTrigger?.addEventListener('click', startFromMenu)
  trigger?.addEventListener('click', show)
  qrTrigger?.addEventListener('click', showQR)
  stopTrigger?.addEventListener('click', stopFromMenu)
  syncButtons()
  el('[data-create]').onclick = create
  el('[data-reset-link]').onclick = resetLink
  if (designKey()) prepareInvitation()
  el('[data-close]').onclick = () => dialog.close()
  el('[data-stop-host]').onclick = () => { void stopHosting().catch(() => {}) }
  return { show, animationFrame: state => animation?.frame(state), animationEvent: event => animation?.event(event), bindJobs(options) {
    jobs?.dispose()
    jobOptions = options
    jobs = initJobSharing({ ...options, ...broadcast, document: doc, fetch: request,
      perspective: controls.perspective,
      getRoom: () => { const share = currentRoom(); return share ? { ...share, capabilities } : null },
      beforeStart: async () => { if (animationActive) throw new Error('Stop the animation before sharing a job.'); nativeTools?.clear(); await nativeTools?.settle(); await stopNative(); await jobs.setPerspective(controls.perspective) },
      onSharedChange: async shared => {
        if (shared) nativeTools?.clear()
        else if (hadSharedJob) { try { nativeTools?.remember() } catch { nativeTools?.clear() } }
        hadSharedJob = !!shared
        if (!shared && controls.perspective && currentRoom()) {
          try { await sharePerspective(true) } catch (error) { controls.setPerspective(false); controls.error(error.message) }
        }
      } })
    void refresh()
    clearInterval(statusTimer)
    statusTimer = setInterval(async () => {
      if (busy || disposed || polling) return
      if (designKey() && !invitation && !invitationFlight) prepareInvitation()
      polling = true
      const ticket = revision
      try {
        const value = await api('status')
        if (!disposed && !busy && !refreshing && ticket === revision) { shares = designShares(value); capabilities = value.capabilities ?? []; connectionStatus(value); renderShares() }
      } catch { /* The next authenticated write reports an interruption. */ }
      finally { polling = false }
    }, 5000)
    return jobs
  }, dispose() { drawings?.dispose(); animation?.dispose(); meetingTarget.dispose(); vrAvatar.dispose(); documentClosed(); unsubscribeDocument?.(); hostWindow?.removeEventListener('nadoc:document-reset', documentClosed); hostWindow?.removeEventListener('pagehide', documentClosed); nativeTools?.dispose(); clearInterval(statusTimer); disposed = true; hostingAbort.abort(new DOMException('Sharing closed', 'AbortError')); preservingPerspective = true; broadcast?.prepared.cancelSharedCamera?.(); jobs?.dispose(); presenter?.dispose(); controls.dispose(); if (oldBroadcast) oldBroadcast.hidden = false; startTrigger?.removeEventListener('click', startFromMenu); trigger?.removeEventListener('click', show); qrTrigger?.removeEventListener('click', showQR); stopTrigger?.removeEventListener('click', stopFromMenu); dialog.remove() } }
}
