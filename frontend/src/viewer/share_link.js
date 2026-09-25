import { waitForPublicHosting } from './hosting_setup.js'
import { requireSharingCapabilities } from './sharing_capabilities.js'
import { initNativeViewToolSharing } from './native_view_tool_sharing.js'
import './sharing_controls.css'
/** Editor-side share UI. Publishes a prepared snapshot through the local host. */
import { initEditorBroadcast } from './editor_broadcast.js'
import { initJobSharing } from './job_sharing.js'
import { initPresentationControls } from './presentation_controls.js'
export function initShareLink({ exportView, broadcast, document: doc = document, fetch: request = fetch, clipboard = navigator.clipboard }) {
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
  dialog.innerHTML = `<header class="sharing-header"><h2 id="share-link-title">Sharing</h2><button class="btn" data-close aria-label="Close">×</button></header>
    <div class="sharing-actions" data-publish-actions><button class="btn btn--primary" data-create>Create link</button><button class="btn btn--danger" data-stop-host disabled>Stop sharing all links</button></div>
    <div data-links class="sharing-actions sharing-links"></div>
    <p class="sharing-status" data-status role="status" aria-live="polite"></p>
    <details class="sharing-error" data-error hidden><summary>Error log</summary><pre data-error-log></pre></details>`
  doc.body.append(dialog)
  const el = selector => dialog.querySelector(selector), status = el('[data-status]'), list = el('[data-links]')
  const hostingAbort = new AbortController()
  let polling = false, busy = false, refreshing = false, disposed = false, revision = 0, selectedId = null, shares = [], capabilities = [], jobs = null, statusTimer = null, jobOptions = null, hadSharedJob = false
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
    el('[data-create]').disabled = busy || refreshing || shares.length > 0
    el('[data-stop-host]').disabled = busy || refreshing || shares.length === 0
    const copy = el('[data-copy-link]')
    if (copy) copy.disabled = busy || refreshing
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
    selectedId = shares.some(share => share.id === selectedId) ? selectedId : shares[0]?.id ?? null
    if (!currentRoom()) list.replaceChildren()
    if (currentRoom() && !el('[data-copy-link]')) {
      const copy = doc.createElement('button')
      copy.className = 'btn'; copy.dataset.copyLink = ''; copy.textContent = 'Copy link'
      copy.onclick = async () => {
        clearError()
        try {
          await clipboard.writeText(currentRoom().url)
          status.textContent = 'Copied'
        } catch (error) { reportError(new Error(`Could not copy link: ${error.message ?? error}`)) }
      }
      list.append(copy)
    }
    if (currentRoom()?.password) {
      let password = el('[data-password]')
      if (!password) {
        password = doc.createElement('p')
        password.className = 'sharing-password'; password.dataset.password = ''
        list.append(password)
      }
      const text = `Password: ${currentRoom().password}`
      if (password.textContent !== text) password.textContent = text
    } else el('[data-password]')?.remove()
    syncButtons()
    syncControls()
  }
  async function refresh() {
    const ticket = ++revision
    refreshing = true; syncButtons()
    try {
      const value = await api('status')
      if (disposed || ticket !== revision) return
      shares = value.running === false ? [] : value.shares ?? []
      capabilities = value.capabilities ?? []
      renderShares()
      if (value.updateRequired) reportError(new Error('Stop sharing all links, then create a new link to load the updated viewer.'))
      else if (shares.length && value.publicAccess?.state !== 'ready' && value.publicAccess) reportError(new Error(value.publicAccess.message))
    } catch (error) { if (!disposed && ticket === revision) reportError(error) }
    finally { if (!disposed && ticket === revision) { refreshing = false; syncButtons() } }
  }
  async function create() {
    if (busy || refreshing || shares.length) return
    revision++; busy = true; clearError(); syncButtons()
    dialog.setAttribute('aria-busy', 'true')
    try {
      await nativeTools?.settle()
      const nativeContext = nativeTools?.capture()
      nativeTools?.clear()
      status.textContent = 'Creating link…'
      const result = await exportView({ presentation: true })
      if (!result) throw new Error('Another export is busy; please retry.')
      const host = await waitForPublicHosting({ api, signal: hostingAbort.signal, onProgress: () => { if (!disposed) status.textContent = 'Connecting…' } })
      capabilities = host.capabilities ?? []
      // Another editor may have created a link while this dialog was connecting.
      if (host.shares?.length) {
        shares = host.shares; renderShares(); status.textContent = ''; return
      }
      requireSharingCapabilities(result, capabilities)
      const share = await api('create', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-NADOC-Title': encodeURIComponent(result.title) }, body: result.buffer })
      if (!disposed) {
        shares = [share]; selectedId = share.id; renderShares()
        if (nativeContext) nativeTools.remember({ ...nativeContext, room: share.id })
        if (controls.perspective) await sharePerspective(true)
        status.textContent = ''
      }
    } catch (error) { if (!disposed) reportError(error) }
    finally { busy = false; if (!disposed) { dialog.setAttribute('aria-busy', 'false'); syncButtons() } }
  }
  const show = () => { dialog.showModal(); if (!busy) refresh() }
  trigger?.addEventListener('click', show)
  el('[data-create]').onclick = create
  el('[data-close]').onclick = () => dialog.close()
  el('[data-stop-host]').onclick = () => { void stopHosting().catch(() => {}) }
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
      if (busy || disposed || polling) return
      polling = true
      const ticket = revision
      try {
        const value = await api('status')
        if (!disposed && !busy && !refreshing && ticket === revision) { shares = value.shares ?? []; capabilities = value.capabilities ?? []; renderShares() }
      } catch { /* The next authenticated write reports an interruption. */ }
      finally { polling = false }
    }, 5000)
    return jobs
  }, dispose() { nativeTools?.dispose(); clearInterval(statusTimer); disposed = true; hostingAbort.abort(new DOMException('Sharing closed', 'AbortError')); preservingPerspective = true; broadcast?.prepared.cancelSharedCamera?.(); jobs?.dispose(); presenter?.dispose(); controls.dispose(); if (oldBroadcast) oldBroadcast.hidden = false; trigger?.removeEventListener('click', show); dialog.remove() } }
}
