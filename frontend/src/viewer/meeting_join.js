/** Invite-only loading for the temporary static host; no editor API dependency. */
export function mountMeetingJoin({ viewer, document: doc = document, location: loc = location, fetch: request = fetch, setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  const params = new URLSearchParams(loc.hash.slice(1)), token = params.get('invite')
  const room = params.get('room')
  const base = room && /^(?:[a-f0-9]{32}|default)$/.test(room) ? `/meeting/${room}` : '/meeting'
  if (!token) return () => {}
  const dialog = doc.getElementById('join'), form = doc.getElementById('join-form')
  const error = doc.getElementById('join-error'), button = doc.getElementById('join-submit')
  const status = doc.getElementById('status'), identity = doc.getElementById('guest')
  const passwordField = doc.getElementById('meeting-password'), passwordRow = doc.getElementById('meeting-password-row')
  const needsPassword = params.get('password') === 'required'
  if (passwordRow) passwordRow.hidden = !needsPassword
  if (passwordField) { passwordField.required = needsPassword; passwordField.value = '' }
  const abort = new AbortController()
  let disposed = false, timer = null, busy = false
  doc.querySelector('.open').hidden = true
  dialog.showModal()
  const preventClose = event => event.preventDefault()
  dialog.addEventListener('cancel', preventClose)
  async function submit(event) {
    event.preventDefault()
    if (busy || disposed) return
    busy = true; button.disabled = true; error.textContent = ''
    try {
      const joined = await request(`${base}/join`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, name: doc.getElementById('guest-name').value.trim(), ...(needsPassword ? { password: passwordField?.value.trim() ?? '' } : {}) }), signal: abort.signal })
      const details = await joined.json()
      if (!joined.ok) throw new Error(details.error || 'Could not join this session')
      button.textContent = 'Loading design…'
      const response = await request(`${base}/scene`, { signal: abort.signal })
      if (!response.ok) throw new Error('The host is unavailable or the session has ended.')
      const size = Number(response.headers.get('Content-Length'))
      if (!Number.isFinite(size) || size <= 0 || size > 512 * 1024 * 1024) throw new Error('Invalid package size')
      const blob = await response.blob()
      if (blob.size !== size) throw new Error('Incomplete package download; please retry')
      if (disposed) return
      const loaded = await viewer.loadFile(new File([blob], 'Shared design.nadocview'))
      if (!loaded) throw new Error(status.textContent || 'Could not open the shared design')
      if (disposed) return
      identity.textContent = `${details.name} · Private test`
      if (passwordField) passwordField.value = ''
      dialog.close()
      timer = repeat(async () => {
        try {
          const response = await request(`${base}/status`, { signal: abort.signal })
          if (!response.ok) throw new Error('ended')
        } catch {
          if (!disposed) { identity.textContent = `${details.name} · Host disconnected or session ended`; cancel(timer); timer = null }
        }
      }, 10000)
    } catch (reason) { if (!disposed) error.textContent = reason.message }
    finally { busy = false; if (!disposed) { button.disabled = false; button.textContent = 'Join view' } }
  }
  form.addEventListener('submit', submit)
  return () => { disposed = true; abort.abort(); if (timer) cancel(timer); form.removeEventListener('submit', submit); dialog.removeEventListener('cancel', preventClose); if (dialog.open) dialog.close() }
}

/** A second invite can change only the fragment in an already-open viewer tab. */
export function mountMeetingInvites({ viewer, window: host = window, ...options }) {
  let unmount = () => {}
  const route = () => { unmount(); unmount = mountMeetingJoin({ viewer, ...options, location: host.location }) }
  host.addEventListener('hashchange', route)
  route()
  return () => { host.removeEventListener('hashchange', route); unmount() }
}
