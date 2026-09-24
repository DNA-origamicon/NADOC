import { mountViewerHealth } from './viewer_health.js'
import { createMeetingPing } from './meeting_ping.js'
/** Invite-only loading for the temporary static host; no editor API dependency. */
import { mountMeetingPresentation } from './meeting_presentation.js'
import { mountMeetingStatus } from './meeting_status.js'
import { mountMeetingPresence } from './meeting_presence.js'
import { mountPresenterAttendance } from './meeting_attendance.js'
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
  const sharedViews = new WeakSet()
  let disposed = false, ended = false, timer = null, polling = false, busy = false, disconnectPresentation = () => {}
  const display = mountMeetingStatus({ viewer, document: doc })
  const ping = createMeetingPing({ document: doc })
  let presence = null, moveView = () => {}
  const health = mountViewerHealth({ viewer, base, document: doc, fetch: request, onChange: value => presence?.setHealth(value) })
  const measuredRequest = health.fetch
  function finish() {
    if (ended || disposed) return
    ended = true; abort.abort(); if (timer) cancel(timer); timer = null
    disconnectPresentation(); health.dispose(); presence?.dispose(); ping.dispose(); display.end(); identity.textContent = 'Presentation ended · Session ended'
    if (dialog.open) dialog.close()
  }
  doc.querySelector('.open').hidden = true
  dialog.showModal()
  const preventClose = event => event.preventDefault()
  dialog.addEventListener('cancel', preventClose)
  const credential = { token, ...(params.get('role') === 'presenter' ? { role: 'presenter' } : {}) }
  async function join(body) {
    const response = await request(`${base}/join`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: abort.signal })
    return { response, details: await response.json() }
  }
  async function loadSharedView(details) {
    if (sharedViews.has(viewer.current) && (!viewer.current?.packageHash || viewer.current.packageHash === details.revision)) return
    const response = await measuredRequest(`${base}/scene`, { signal: abort.signal })
    if (!response.ok) throw new Error('The host is unavailable or the session has ended.')
    const size = Number(response.headers.get('Content-Length'))
    if (!Number.isFinite(size) || size <= 0 || size > 512 * 1024 * 1024) throw new Error('Invalid package size')
    const blob = await response.blob()
    if (blob.size !== size) throw new Error('Incomplete package download; please retry')
    if (disposed) return
    const loaded = await viewer.loadFile(new File([blob], 'Shared design.nadocview'))
    if (!loaded) throw new Error(status.textContent || 'Could not open the shared design')
    if (details.revision && viewer.current?.packageHash && viewer.current.packageHash !== details.revision) throw new Error('Downloaded design does not match this invitation')
    if (viewer.current) sharedViews.add(viewer.current)
  }
  async function enter(resume = false) {
    if (busy || disposed || ended) return
    busy = true; button.disabled = true; error.textContent = ''
    button.textContent = resume ? 'Checking existing session…' : 'Joining…'
    try {
      const { response, details } = await join(resume ? { ...credential, resume: true } : {
        ...credential, name: doc.getElementById('guest-name').value.trim(), ...(needsPassword ? { password: passwordField?.value.trim() ?? '' } : {}) })
      if (disposed) return
      if (!response.ok) {
        if (resume && [401, 403, 404, 405].includes(response.status)) return
        throw new Error(details.error || 'Could not join this session')
      }
      button.textContent = 'Loading design…'
      await loadSharedView(details)
      if (disposed) return
      identity.textContent = `${details.name} · Private test`
      if (passwordField) passwordField.value = ''
      dialog.close()
      presence?.dispose()
      presence = mountMeetingPresence({ parent: doc.querySelector('main') ?? doc.body, selfId: details.participantId, onView: view => moveView(view), ping, document: doc })
      if (details.role && details.revision) {
        const mount = ({ onSharedView } = {}) => mountMeetingPresentation({ onEnded: finish, onLoading: display.progress, onPresence: (participants, context) => { presence.update(participants, context); if (details.role === 'guest') health.start() }, onViewShared: ping.play, onViewReady: move => { moveView = move }, onSharedView, viewer, base, role: details.role, revision: details.revision, room: room || 'default', document: doc, fetch: measuredRequest })
        disconnectPresentation = details.role === 'presenter' ? mountPresenterAttendance({ viewer, base, document: doc, fetch: request, mount, resume: async () => {
          const resumed = await join({ ...credential, resume: true })
          if (!resumed.response.ok) throw new Error(resumed.details.error || 'Could not return to the presentation')
          details.revision = resumed.details.revision
          await loadSharedView(details)
        } }) : mount()
      }
      timer = repeat(async () => {
        if (disposed || ended || polling) return
        polling = true
        try {
          const response = await measuredRequest(`${base}/status`, { signal: abort.signal })
          if ([401, 403, 404, 410].includes(response.status)) {
            finish()
            return
          }
          if (!response.ok) throw new Error('ended')
          if (!disposed && !ended) identity.textContent = `${details.name} · Private test`
        } catch {
          // A transient outage must not disable EventSource's reconnect or local navigation.
          if (!disposed && !ended) identity.textContent = `${details.name} · Host disconnected; reconnecting…`
        } finally { polling = false }
      }, 10000)
    } catch (reason) { if (!disposed) error.textContent = reason.message }
    finally { busy = false; if (!disposed) { button.disabled = false; button.textContent = 'Join view' } }
  }
  const submit = event => { event.preventDefault(); void enter() }
  form.addEventListener('submit', submit)
  void enter(true)
  return () => { disposed = true; abort.abort(); disconnectPresentation(); health.dispose(); presence?.dispose(); ping.dispose(); display.dispose(); if (timer) cancel(timer); form.removeEventListener('submit', submit); dialog.removeEventListener('cancel', preventClose); if (dialog.open) dialog.close() }
}

/** A second invite can change only the fragment in an already-open viewer tab. */
export function mountMeetingInvites({ viewer, window: host = window, ...options }) {
  let unmount = () => {}
  const route = () => { unmount(); unmount = mountMeetingJoin({ viewer, ...options, location: host.location }) }
  host.addEventListener('hashchange', route)
  route()
  return () => { host.removeEventListener('hashchange', route); unmount() }
}
