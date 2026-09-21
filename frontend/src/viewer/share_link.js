/** Editor-side share UI. Publishes a prepared snapshot through the local host. */
export function initShareLink({ exportView, document: doc = document, fetch: request = fetch, clipboard = navigator.clipboard }) {
  const trigger = doc.getElementById('menu-help-share-link')
  const dialog = doc.createElement('dialog')
  dialog.id = 'share-link-dialog'
  dialog.style.cssText = 'width:min(680px,90vw);max-height:85vh;overflow:auto;background:#161b22;color:#e6edf3;border:1px solid #484f58;border-radius:10px;padding:22px'
  dialog.innerHTML = `<h2 style="margin-top:0">Share a prepared view</h2><p>Create an internet link to a snapshot of the current 3D view. Guests need only a browser, the invitation, and its password. Later edits do not change an existing link.</p><p>Keep this PC awake while sharing. Up to four participants, including the presenter. Open presenter to share your perspective; guests choose Jump or Follow. Shared highlights and trajectories are coming later.</p><button data-create>Create link for current view</button> <button data-stop-host>Stop hosting all links</button> <button data-close>Close</button><p data-status role="status"></p><div data-links></div>`
  doc.body.append(dialog)
  const el = selector => dialog.querySelector(selector), status = el('[data-status]'), list = el('[data-links]')
  let busy = false, disposed = false, revision = 0
  async function api(path, options = {}) {
    const response = await request(`/__nadoc_share/${path}`, { ...options, headers: { 'X-NADOC-Share': '1', ...options.headers } })
    const value = await response.json()
    if (!response.ok) throw new Error(value.error || 'Could not contact the local sharing host')
    return value
  }
  function row(share) {
    const section = doc.createElement('section'); section.style.cssText = 'border-top:1px solid #484f58;margin-top:16px;padding-top:12px'
    const title = doc.createElement('strong'); title.textContent = share.title
    const expiry = doc.createElement('p'); expiry.textContent = `Expires ${new Date(share.expiresAt).toLocaleString()}`
    const url = doc.createElement('input'); url.readOnly = true; url.value = share.url; url.setAttribute('aria-label', `Link for ${share.title}`); url.style.cssText = 'display:block;width:100%;padding:8px;margin:8px 0'
    const copy = doc.createElement('button'); copy.textContent = 'Copy link'
    copy.onclick = async () => { url.focus(); url.select(); try { await clipboard.writeText(share.url); status.textContent = share.password ? 'Link copied. Send the meeting password too, or choose Copy invitation.' : 'Link copied. Open it in a browser and enter a display name.' } catch { status.textContent = 'Link selected. Press Ctrl-C (or Command-C) to copy.' } }
    const open = doc.createElement('a'); open.textContent = 'Open viewer'; open.href = share.url; open.target = '_blank'; open.rel = 'noopener noreferrer'; open.style.cssText = 'margin:0 16px;color:#58a6ff'
    const stop = doc.createElement('button'); stop.textContent = 'Stop sharing'
    stop.onclick = async () => { stop.disabled = true; try { await api(`shares/${share.id}`, { method: 'DELETE' }); section.remove(); status.textContent = 'Link stopped. Already downloaded views can remain on guest devices.' } catch (error) { status.textContent = error.message; stop.disabled = false } }
    section.append(title, expiry, url, copy, open, stop)
    if (share.presenterUrl) {
      const presenter = doc.createElement('a'); presenter.textContent = 'Open presenter'; presenter.href = share.presenterUrl; presenter.target = '_blank'; presenter.rel = 'noopener noreferrer'; presenter.style.cssText = 'margin:0 12px;color:#58a6ff'; section.append(presenter)
    }
    if (share.password) {
      const password = doc.createElement('p'); password.textContent = `Meeting password: ${share.password}`; password.dataset.password = share.password
      const invitation = doc.createElement('textarea'); invitation.readOnly = true; invitation.hidden = true; invitation.setAttribute('aria-label', 'Invitation to copy')
      invitation.value = `Join ${share.title}\n${share.url}\nMeeting password: ${share.password}\nOpen the link in your browser, then enter your name and the password. No installation or account needed.`
      const copyInvitation = doc.createElement('button'); copyInvitation.textContent = 'Copy invitation'
      copyInvitation.onclick = async () => { try { await clipboard.writeText(invitation.value); status.textContent = 'Invitation copied, including the link and password.' } catch { invitation.hidden = false; invitation.focus(); invitation.select(); status.textContent = 'Invitation selected. Press Ctrl-C (or Command-C) to copy.' } }
      section.append(password, copyInvitation, invitation)
    }
    return section
  }
  async function refresh() {
    const ticket = ++revision
    try { const value = await api('status'); if (value.running === false) throw new Error('Host is offline'); if (!disposed && ticket === revision) { list.replaceChildren(...value.shares.map(row)); status.textContent = value.shares.length ? 'Active snapshot links on this host.' : 'Host ready. Create a link for the current view.' } }
    catch { if (!disposed && ticket === revision) { list.replaceChildren(); status.textContent = 'Create a link to start a two-hour internet sharing session. First use may require Tailscale account approval on this hosting PC only.' } }
  }
  async function create() {
    if (busy) return
    revision++; busy = true; el('[data-create]').disabled = true; el('[data-stop-host]').disabled = true
    try {
      status.textContent = 'Preparing current view…'
      const result = await exportView()
      if (!result) throw new Error('Another export is busy; please retry.')
      status.textContent = 'Connecting internet sharing…'
      await api('start', { method: 'POST' })
      status.textContent = 'Publishing prepared view…'
      const share = await api('create', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-NADOC-Title': encodeURIComponent(result.title) }, body: result.buffer })
      if (!disposed) { list.prepend(row(share)); status.textContent = 'Invitation ready. Send it to your guests.' }
    } catch (error) { if (!disposed) status.textContent = error.message }
    finally { busy = false; el('[data-create]').disabled = false; el('[data-stop-host]').disabled = false }
  }
  const show = () => { dialog.showModal(); if (!busy) refresh() }
  trigger?.addEventListener('click', show)
  el('[data-create]').onclick = create
  el('[data-close]').onclick = () => dialog.close()
  el('[data-stop-host]').onclick = async () => { try { await api('stop', { method: 'POST' }); list.replaceChildren(); status.textContent = 'Hosting stopped. All links have ended.' } catch (error) { status.textContent = error.message } }
  return { show, dispose() { disposed = true; trigger?.removeEventListener('click', show); dialog.remove() } }
}
