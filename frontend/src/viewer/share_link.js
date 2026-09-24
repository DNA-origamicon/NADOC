import { requireSharingCapabilities } from './sharing_capabilities.js'
import { initNativeViewToolSharing } from './native_view_tool_sharing.js'
import './sharing_controls.css'
/** Editor-side share UI. Publishes a prepared snapshot through the local host. */
import { mountTrajectoryShare, appendTrajectoryControls } from './trajectory_share_ui.js'
import { initEditorBroadcast } from './editor_broadcast.js'
import { initJobSharing } from './job_sharing.js'
import { initPresentationControls } from './presentation_controls.js'
export function initShareLink({ exportView, broadcast, trajectory, document: doc = document, fetch: request = fetch, clipboard = navigator.clipboard }) {
  let preservingPerspective = false, nativeFlight = null
  const presenter = broadcast ? initEditorBroadcast({ ...broadcast, document: doc, fetch: request, embedded: true, onStop: reason => {
    if (!preservingPerspective) { const wasSharing = controls.perspective; controls.setPerspective(false); if (wasSharing) controls.error(reason) }
  } }) : null
  const oldBroadcast = doc.getElementById('menu-help-broadcast')
  if (oldBroadcast) oldBroadcast.hidden = true
  const trigger = doc.getElementById('menu-file-sharing')
  const dialog = doc.createElement('dialog')
  dialog.id = 'share-link-dialog'
  dialog.className = 'sharing-dialog'
  dialog.setAttribute('aria-labelledby', 'share-link-title')
  dialog.innerHTML = `<header class="sharing-header"><h2 id="share-link-title">Share presentation</h2><button class="btn" data-close>Close</button></header>
    <p class="sharing-description">Send a browser invitation to up to three guests. They can explore independently, with no installation or account.</p>
    <div class="sharing-card"><h3>Current view</h3><p class="sharing-description">Create one invitation for your presentation. Representations, multi-overlay, view volumes, view tools, and annotations stay in sync while this design is shared. Share a simulation job from its Visualizations card; guests keep this link and sign-in when you switch jobs.</p><label class="sharing-field">Presentation<select class="select" data-target><option value="">New invitation</option></select></label></div>
    <div class="sharing-actions sharing-publish" data-publish-actions><button class="btn btn--primary" data-create>Create link for current view</button></div>
    <p class="sharing-status" data-status role="status" aria-live="polite"></p><div data-links class="sharing-links" aria-label="Active share links"></div>
    <footer class="sharing-footer"><p class="sharing-description">Keep this PC awake while sharing. Leaving the presentation keeps guests signed in until you stop hosting or the session expires.</p><button class="btn btn--danger" data-stop-host>Stop hosting all links</button></footer>`
  doc.body.append(dialog)
  const el = selector => dialog.querySelector(selector), status = el('[data-status]'), list = el('[data-links]')
  const clipUi = trajectory ? mountTrajectoryShare({ dialog, ...trajectory, document: doc }) : null
  let polling = false, busy = false, disposed = false, revision = 0, selectedId = null, shares = [], capabilities = [], jobs = null, statusTimer = null, jobOptions = null, hadSharedJob = false
  const currentRoom = () => shares.find(s => s.id === selectedId) ?? shares[0]
  async function stopNative() {
    preservingPerspective = true
    try { await presenter?.stop(); await nativeFlight?.catch(() => {}) } finally { preservingPerspective = false }
  }
  async function sharePerspective(enabled) {
    if (jobs?.active) return jobs.setPerspective(enabled)
    if (!enabled) return stopNative()
    const share = currentRoom()
    if (!share || !presenter) throw new Error('Create a presentation link in an open design first.')
    nativeFlight = presenter.present(share)
    try { await nativeFlight } finally { nativeFlight = null }
  }
  const controls = initPresentationControls({ document: doc, onPerspective: sharePerspective, onEnd: stopHosting, onGuestView: view => {
    try {
      broadcast?.prepared.viewSharedCamera(view.camera, { presentation: !jobs?.active, canMove: () => !!currentRoom() && (!jobs?.active || jobs.canViewShared) })
    } catch (error) { controls.error(error.message) }
  } })
  const nativeTools = broadcast?.prepared ? initNativeViewToolSharing({
    prepared: broadcast.prepared, store: broadcast.store, getRoom: currentRoom,
    getContext: () => ({ selection: jobOptions?.getSelection?.(),
      active: ['oxdna', 'namd'].map(engine => jobOptions?.getSource?.(engine)?.controller?.activeJobId?.() ?? null),
      modes: [...doc.querySelectorAll('input[id^="oxdna-jobs-viz-"], input[id^="md-jobs-viz-"]')].filter(input => input.checked).map(input => input.id) }),
    isBusy: () => busy || !!jobs?.active,
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
  function syncControls() {
    controls.setActive(shares.length > 0)
    controls.setParticipants(currentRoom()?.participants ?? [], { serverTime: currentRoom()?.serverTime })
    if (!shares.length) void stopNative()
    jobs?.refresh()
  }
  async function stopHosting() {
    nativeTools?.clear()
    await nativeTools?.settle()
    broadcast?.prepared.cancelSharedCamera?.()
    await api('stop', { method: 'POST' })
    shares = []; selectedId = null; renderShares()
    status.textContent = 'Hosting stopped. All links have ended.'
  }
  async function api(path, options = {}) {
    const response = await request(`/__nadoc_share/${path}`, { ...options, headers: { 'X-NADOC-Share': '1', ...options.headers } })
    const value = await response.json()
    if (!response.ok) throw new Error(value.error || 'Could not contact the local sharing host')
    return value
  }
  function chooseTarget() {
    selectedId = el('[data-target]').value
    controls.setParticipants(currentRoom()?.participants ?? [], { serverTime: currentRoom()?.serverTime })
    el('[data-create]').textContent = selectedId ? 'Update shared view' : 'Create link for current view'
  }
  function renderShares() {
    list.replaceChildren(...shares.map(row))
    const options = shares.length ? shares : [{ id: '', title: 'Create presentation invitation' }]
    el('[data-target]').replaceChildren(...options.map(share => { const option = doc.createElement('option'); option.value = share.id; option.textContent = share.title; return option }))
    if (selectedId === null) selectedId = shares[0]?.id ?? ''
    el('[data-target]').value = shares.some(share => share.id === selectedId) ? selectedId : ''
    chooseTarget()
    syncControls()
  }
  function row(share) {
    const section = doc.createElement('section'); section.className = 'sharing-card sharing-link'
    const actions = doc.createElement('div'); actions.className = 'sharing-actions'
    const title = doc.createElement('strong'); title.textContent = share.title
    const expiry = doc.createElement('p'); expiry.className = 'sharing-description'; expiry.textContent = `Expires ${new Date(share.expiresAt).toLocaleString()}`
    const url = doc.createElement('input'); url.readOnly = true; url.value = share.url; url.setAttribute('aria-label', `Link for ${share.title}`); url.className = 'input input--mono sharing-url'
    const copy = doc.createElement('button'); copy.className = share.password ? 'btn' : 'btn btn--primary'; copy.textContent = 'Copy link'
    copy.onclick = async () => { url.focus(); url.select(); try { await clipboard.writeText(share.url); status.textContent = share.password ? 'Link copied. Send the meeting password too, or choose Copy invitation.' : 'Link copied. Open it in a browser and enter a display name.' } catch { status.textContent = 'Link selected. Press Ctrl-C (or Command-C) to copy.' } }
    const open = doc.createElement('a'); open.textContent = 'Open viewer'; open.href = share.url; open.target = '_blank'; open.rel = 'noopener noreferrer'; open.className = 'btn'
    const stop = doc.createElement('button'); stop.className = 'btn btn--danger'; stop.textContent = 'End invitation'
    stop.onclick = async () => { stop.disabled = true; try { await api(`shares/${share.id}`, { method: 'DELETE' }); shares = shares.filter(value => value.id !== share.id); if (selectedId === share.id) selectedId = null; renderShares(); status.textContent = 'Link stopped. Already downloaded views can remain on guest devices.' } catch (error) { status.textContent = error.message; stop.disabled = false } }
    section.append(title, expiry, url, actions)
    actions.append(copy, open)
    if (share.password) {
      const password = doc.createElement('p'); password.className = 'sharing-password'; password.textContent = `Meeting password: ${share.password}`; password.dataset.password = share.password
      const invitation = doc.createElement('textarea'); invitation.className = 'input sharing-invitation'; invitation.readOnly = true; invitation.hidden = true; invitation.setAttribute('aria-label', 'Invitation to copy')
      invitation.value = `Join ${share.title}\n${share.url}\nMeeting password: ${share.password}\nOpen the link in your browser, then enter your name and the password. No installation or account needed.`
      const copyInvitation = doc.createElement('button'); copyInvitation.className = 'btn btn--primary'; copyInvitation.textContent = 'Copy invitation'
      copyInvitation.onclick = async () => { try { await clipboard.writeText(invitation.value); status.textContent = 'Invitation copied, including the link and password.' } catch { invitation.hidden = false; invitation.focus(); invitation.select(); status.textContent = 'Invitation selected. Press Ctrl-C (or Command-C) to copy.' } }
      section.insertBefore(password, actions); actions.prepend(copyInvitation); section.append(invitation)
    }
    actions.append(stop)
    appendTrajectoryControls({ section, share, api, status, document: doc })
    return section
  }
  async function refresh() {
    const ticket = ++revision
    el('[data-create]').disabled = true; el('[data-target]').disabled = true
    try { const value = await api('status'); if (value.running === false) throw new Error('Host is offline'); if (!disposed && ticket === revision) { shares = value.shares; capabilities = value.capabilities ?? []; renderShares(); status.textContent = value.updateRequired ? 'Sharing host update required. Stop hosting, then create a new link to load the current viewer.' : value.shares.length ? 'Update this presentation without changing the guest invitation.' : 'Host ready. Create a link for the current view.' } }
    catch { if (!disposed && ticket === revision) { shares = []; selectedId = null; renderShares(); status.textContent = 'Create a link to start a two-hour internet sharing session. First use may require Tailscale account approval on this hosting PC only.' } }
    finally { if (!disposed && ticket === revision && !busy) { el('[data-create]').disabled = false; el('[data-target]').disabled = false } }
  }
  async function create() {
    if (busy) return
    const asClip = !!clipUi?.enabled
    let target = selectedId
    revision++; busy = true; dialog.setAttribute('aria-busy', 'true'); clipUi?.setBusy(true); el('[data-target]').disabled = true; el('[data-create]').disabled = true; el('[data-stop-host]').disabled = true
    try {
      await nativeTools?.settle()
      if (target) await stopNative()
      if (jobs?.active) throw new Error('Select the shared job and click Stop sharing before replacing the presentation view.')
      const nativeContext = !asClip ? nativeTools?.capture() : null
      nativeTools?.clear()
      status.textContent = 'Preparing current view…'
      const result = asClip ? await clipUi.prepare((done, total, bytes) => { status.textContent = `Preparing trajectory ${done}/${total} · ${(bytes / 1048576).toFixed(1)} MiB` }) : await exportView({ presentation: true })
      if (!result) throw new Error('Another export is busy; please retry.')
      status.textContent = 'Connecting internet sharing…'
      const host = await api('start', { method: 'POST' })
      capabilities = host.capabilities ?? []
      // A host upgrade revokes old invitations; publish a fresh one in this operation.
      if (target && Array.isArray(host.shares) && !host.shares.some(share => share.id === target)) {
        target = null; selectedId = null; shares = host.shares
      }
      if (target && !host.capabilities?.includes('share-content-v1')) throw new Error('This running host predates same-link updates. After this meeting, stop hosting and create a new link once to enable them.')
      requireSharingCapabilities(result, host.capabilities)
      if (asClip && !host.capabilities?.includes('trajectory-clip-v1')) throw new Error('This host predates trajectory sharing. Stop hosting all links after your meeting, then create the trajectory link again.')
      status.textContent = 'Publishing prepared view…'
      const share = await api(target ? `shares/${target}/content` : 'create', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-NADOC-Title': encodeURIComponent(result.title) }, body: result.buffer })
      if (!disposed) { shares = [share, ...shares.filter(value => value.id !== share.id)]; selectedId = share.id; renderShares(); if (nativeContext) nativeTools.remember({ ...nativeContext, room: share.id }); if (controls.perspective) await sharePerspective(true); status.textContent = target ? 'Shared view updated. Guests keep the same link and sign-in.' : 'Invitation ready. Send it to your guests.' }
    } catch (error) { if (!disposed) status.textContent = error.message }
    finally { busy = false; dialog.setAttribute('aria-busy', 'false'); clipUi?.setBusy(false); el('[data-target]').disabled = false; el('[data-create]').disabled = false; el('[data-stop-host]').disabled = false }
  }
  const show = () => { dialog.showModal(); if (!busy) refresh() }
  trigger?.addEventListener('click', show)
  el('[data-create]').onclick = create
  el('[data-target]').onchange = chooseTarget
  el('[data-close]').onclick = () => dialog.close()
  el('[data-stop-host]').onclick = async () => { try { await stopHosting() } catch (error) { status.textContent = error.message } }
  return { show, bindJobs(options) {
    jobs?.dispose()
    jobOptions = options
    jobs = initJobSharing({ ...options, ...broadcast, document: doc, fetch: request,
      perspective: controls.perspective,
      getRoom: () => { const share = currentRoom(); return share ? { ...share, capabilities } : null },
      beforeStart: async () => { nativeTools?.clear(); await nativeTools?.settle(); await stopNative(); await jobs.setPerspective(controls.perspective) },
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
      if (busy || disposed || dialog.open || polling) return
      polling = true
      try {
        const value = await api('status')
        if (!disposed && !busy && !dialog.open) { shares = value.shares ?? []; capabilities = value.capabilities ?? []; syncControls() }
      } catch { /* The next authenticated write reports an interruption. */ }
      finally { polling = false }
    }, 5000)
    return jobs
  }, dispose() { nativeTools?.dispose(); clearInterval(statusTimer); disposed = true; preservingPerspective = true; broadcast?.prepared.cancelSharedCamera?.(); jobs?.dispose(); clipUi?.dispose(); presenter?.dispose(); controls.dispose(); if (oldBroadcast) oldBroadcast.hidden = false; trigger?.removeEventListener('click', show); dialog.remove() } }
}
