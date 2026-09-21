import './sharing_controls.css'
/** Editor-side share UI. Publishes a prepared snapshot through the local host. */
import { mountTrajectoryShare, appendTrajectoryControls } from './trajectory_share_ui.js'
import { initEditorBroadcast } from './editor_broadcast.js'
export function initShareLink({ exportView, broadcast, trajectory, document: doc = document, fetch: request = fetch, clipboard = navigator.clipboard }) {
  const presenter = broadcast ? initEditorBroadcast({ ...broadcast, document: doc, fetch: request }) : null
  const trigger = doc.getElementById('menu-help-share-link')
  const dialog = doc.createElement('dialog')
  dialog.id = 'share-link-dialog'
  dialog.className = 'sharing-dialog'
  dialog.setAttribute('aria-labelledby', 'share-link-title')
  dialog.innerHTML = `<header class="sharing-header"><h2 id="share-link-title">Share a prepared view</h2><button class="btn" data-close>Close</button></header>
    <p class="sharing-description">Send a browser invitation to up to three guests. They can explore independently, with no installation or account.</p>
    <div class="sharing-card"><h3>Current view</h3><p class="sharing-description">Share the visible design or include a recorded trajectory. Update an existing presentation to keep the same guest link and sign-in. Other edits stay private unless you enable Broadcast to presentation.</p><label class="sharing-field">Presentation<select class="select" data-target><option value="">New invitation</option></select></label></div>
    <div class="sharing-actions sharing-publish" data-publish-actions><button class="btn btn--primary" data-create>Create link for current view</button></div>
    <p class="sharing-status" data-status role="status" aria-live="polite"></p><div data-links class="sharing-links" aria-label="Active share links"></div>
    <footer class="sharing-footer"><p class="sharing-description">Keep this PC awake while sharing. Leaving the presentation keeps guests signed in until you stop hosting or the session expires.</p><button class="btn btn--danger" data-stop-host>Stop hosting all links</button></footer>`
  doc.body.append(dialog)
  const el = selector => dialog.querySelector(selector), status = el('[data-status]'), list = el('[data-links]')
  const clipUi = trajectory ? mountTrajectoryShare({ dialog, ...trajectory, document: doc }) : null
  let busy = false, disposed = false, revision = 0, selectedId = null, shares = []
  async function api(path, options = {}) {
    const response = await request(`/__nadoc_share/${path}`, { ...options, headers: { 'X-NADOC-Share': '1', ...options.headers } })
    const value = await response.json()
    if (!response.ok) throw new Error(value.error || 'Could not contact the local sharing host')
    return value
  }
  function chooseTarget() {
    selectedId = el('[data-target]').value
    el('[data-create]').textContent = selectedId ? 'Update shared view' : 'Create link for current view'
  }
  function renderShares() {
    list.replaceChildren(...shares.map(row))
    const options = [{ id: '', title: 'New invitation' }, ...shares]
    el('[data-target]').replaceChildren(...options.map(share => { const option = doc.createElement('option'); option.value = share.id; option.textContent = share.title; return option }))
    if (selectedId === null) selectedId = shares[0]?.id ?? ''
    el('[data-target]').value = shares.some(share => share.id === selectedId) ? selectedId : ''
    chooseTarget()
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
    const stop = doc.createElement('button'); stop.className = 'btn btn--danger'; stop.textContent = 'Stop sharing'
    stop.onclick = async () => { stop.disabled = true; try { await api(`shares/${share.id}`, { method: 'DELETE' }); shares = shares.filter(value => value.id !== share.id); if (selectedId === share.id) selectedId = null; renderShares(); status.textContent = 'Link stopped. Already downloaded views can remain on guest devices.' } catch (error) { status.textContent = error.message; stop.disabled = false } }
    section.append(title, expiry, url, actions)
    actions.append(copy, open)
    if (share.presenterUrl) {
      const presenter = doc.createElement('a'); presenter.textContent = 'Open presenter'; presenter.href = share.presenterUrl; presenter.target = '_blank'; presenter.rel = 'noopener noreferrer'; presenter.className = 'btn'; actions.append(presenter)
    }
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
    try { const value = await api('status'); if (value.running === false) throw new Error('Host is offline'); if (!disposed && ticket === revision) { shares = value.shares; renderShares(); status.textContent = value.shares.length ? 'Update this presentation without changing the guest invitation.' : 'Host ready. Create a link for the current view.' } }
    catch { if (!disposed && ticket === revision) { shares = []; selectedId = null; renderShares(); status.textContent = 'Create a link to start a two-hour internet sharing session. First use may require Tailscale account approval on this hosting PC only.' } }
    finally { if (!disposed && ticket === revision && !busy) { el('[data-create]').disabled = false; el('[data-target]').disabled = false } }
  }
  async function create() {
    if (busy) return
    const asClip = !!clipUi?.enabled, target = selectedId
    revision++; busy = true; dialog.setAttribute('aria-busy', 'true'); clipUi?.setBusy(true); el('[data-target]').disabled = true; el('[data-create]').disabled = true; el('[data-stop-host]').disabled = true
    try {
      if (target && presenter?.active) throw new Error('Turn off Broadcast to presentation before updating this shared view.')
      status.textContent = 'Preparing current view…'
      const result = asClip ? await clipUi.prepare((done, total, bytes) => { status.textContent = `Preparing trajectory ${done}/${total} · ${(bytes / 1048576).toFixed(1)} MiB` }) : await exportView()
      if (!result) throw new Error('Another export is busy; please retry.')
      status.textContent = 'Connecting internet sharing…'
      const host = await api('start', { method: 'POST' })
      if (target && !host.capabilities?.includes('share-content-v1')) throw new Error('This running host predates same-link updates. After this meeting, stop hosting and create a new link once to enable them.')
      if (result.requiresSectionViewer && !host.capabilities?.includes('editor-broadcast-v1')) throw new Error('This running host predates sectioned views. After your current meeting, stop hosting and create a new link to share this sectioned view.')
      if (asClip && !host.capabilities?.includes('trajectory-clip-v1')) throw new Error('This host predates trajectory sharing. Stop hosting all links after your meeting, then create the trajectory link again.')
      status.textContent = 'Publishing prepared view…'
      const share = await api(target ? `shares/${target}/content` : 'create', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-NADOC-Title': encodeURIComponent(result.title) }, body: result.buffer })
      if (!disposed) { shares = [share, ...shares.filter(value => value.id !== share.id)]; selectedId = share.id; renderShares(); status.textContent = target ? 'Shared view updated. Guests keep the same link and sign-in.' : 'Invitation ready. Send it to your guests.' }
    } catch (error) { if (!disposed) status.textContent = error.message }
    finally { busy = false; dialog.setAttribute('aria-busy', 'false'); clipUi?.setBusy(false); el('[data-target]').disabled = false; el('[data-create]').disabled = false; el('[data-stop-host]').disabled = false }
  }
  const show = () => { dialog.showModal(); if (!busy) refresh() }
  trigger?.addEventListener('click', show)
  el('[data-create]').onclick = create
  el('[data-target]').onchange = chooseTarget
  el('[data-close]').onclick = () => dialog.close()
  el('[data-stop-host]').onclick = async () => { try { await api('stop', { method: 'POST' }); shares = []; selectedId = null; renderShares(); status.textContent = 'Hosting stopped. All links have ended.' } catch (error) { status.textContent = error.message } }
  return { show, dispose() { clipUi?.dispose(); presenter?.dispose(); disposed = true; trigger?.removeEventListener('click', show); dialog.remove() } }
}
