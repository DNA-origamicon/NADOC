/** Guest admission UI: waiting never subscribes to or downloads the presentation. */
export function mountMeetingAdmission({ details, base, document: doc = document, fetch: request = fetch,
  setInterval: repeat = setInterval, clearInterval: cancel = clearInterval, onActive, onSuspend, onRejoin, onEnded, onReleased = () => {} }) {
  const panel = doc.createElement('section'); panel.id = 'guest-admission'; panel.hidden = true
  panel.style.cssText = 'position:fixed;inset:0;z-index:1100;background:#0d1117;color:#e6edf3;padding:24px;text-align:center;align-content:center;font:16px system-ui'
  panel.innerHTML = '<h2 data-title></h2><p data-message role="status" aria-live="polite"></p><button class="btn" data-accept>Join now</button> <button class="btn" data-rejoin>Join again</button> <button class="btn" data-cancel>Leave waiting list</button>'
  const bar = doc.createElement('div'); bar.id = 'guest-admission-controls'
  bar.style.cssText = 'position:fixed;bottom:12px;right:12px;z-index:101;background:#161b22;color:white;padding:8px;border-radius:8px'
  bar.innerHTML = '<span data-prompt hidden>Still watching? </span><button class="btn" data-stay hidden>I’m still watching</button> <button class="btn" data-leave>Leave presentation</button>'
  doc.body.append(panel,bar)
  const el = s => panel.querySelector(s), main = doc.querySelector('main'), host = doc.defaultView
  let generation = 0, queuedAction = null
  let state = details.admission, disposed = false, pending = false, viewing = false, activity = true, released = false, timer
  const abort = new AbortController()
  const reasons = { rotated: 'The presenter is welcoming new guests. You can join again.', removed: 'The presenter released your place.',
    background: 'Your place was released while this page was in the background.', disconnected: 'Your connection timed out.',
    inactive: 'Your place was released to welcome waiting guests.', 'offer-expired': 'Your invitation to join expired.', left: 'You left the presentation.' }
  function suspend() { if (viewing) { generation++; viewing = false; onSuspend() } }
  async function paint(value) {
    if (disposed) return
    details = value; state = value.admission
    if (state.state === 'released' && !released) { released = true; onReleased() }
    if (state.state === 'active' && !doc.hidden) {
      panel.hidden = true; bar.hidden = false; if (main) main.inert = false
      const prompt = state.promptUntil != null
      bar.querySelector('[data-prompt]').hidden = !prompt; bar.querySelector('[data-stay]').hidden = !prompt
      if (prompt) bar.querySelector('[data-prompt]').textContent = `Still watching? Your place will be released in ${Math.max(0,Math.ceil((state.promptUntil-state.serverTime)/1000))} seconds. `
      if (!viewing) {
        const ticket = ++generation; viewing = true
        Promise.resolve().then(() => { if (!disposed && ticket === generation) return onActive(value) }).catch(error => {
          if (disposed || ticket !== generation) return
          viewing = false; panel.hidden = false
          el('[data-title]').textContent = 'Reconnecting'; el('[data-message]').textContent = error.message
        })
      }
      return
    }
    suspend(); bar.hidden = true
    // Background pages hold their reservation briefly, without a live scene feed.
    panel.hidden = state.state === 'active'; if (main) main.inert = !panel.hidden
    el('[data-title]').textContent = state.state === 'waiting' ? 'Waiting for a place' : state.state === 'offered' ? 'Your place is ready' : 'Your place was released'
    el('[data-message]').textContent = state.state === 'waiting' ? `You are number ${state.position} in line. Keep this page open; no model is downloaded while you wait.` : state.state === 'offered' ? `Choose Join now within ${Math.max(0, Math.ceil((state.offerUntil-state.serverTime)/1000))} seconds.` : reasons[state.reason] ?? 'Join again when you are ready.'
    el('[data-accept]').hidden = state.state !== 'offered'; el('[data-rejoin]').hidden = state.state !== 'released'; el('[data-cancel]').hidden = !['waiting','offered'].includes(state.state)
  }
  async function pulse(action) {
    if (disposed) return
    if (pending) { queuedAction = action ?? queuedAction ?? ''; return }
    pending = true
    const active = activity; activity = false
    try {
      const response = await request(`${base}/admission`, { method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ visible: !doc.hidden, active: active && !doc.hidden, ...(action ? {action} : {}) }), signal: abort.signal, keepalive: action === 'leave' })
      if ([404,410].includes(response.status)) { onEnded(); return }
      if ([401,403].includes(response.status)) { suspend(); await paint({...details, admission: {state:'released',reason:'disconnected'}}); return }
      if (!response.ok) throw Error('Unable to contact the host. Reconnecting…')
      const value = await response.json()
      await paint(value)
    } catch (error) { if (!disposed) { activity ||= active; if (!panel.hidden) el('[data-message]').textContent = error.message } }
    finally { pending = false; if (queuedAction !== null && !disposed) { const next = queuedAction; queuedAction = null; void pulse(next) } }
  }
  const interacted = event => { if (event.isTrusted) activity = true }
  for (const type of ['pointerdown','keydown','wheel']) doc.addEventListener(type,interacted,{passive:true})
  const visibility = () => { if (doc.hidden) suspend(); void pulse() }
  const pagehide = () => { suspend(); void pulse('leave') }
  doc.addEventListener('visibilitychange',visibility); host?.addEventListener('pagehide',pagehide)
  el('[data-accept]').onclick = () => pulse('accept')
  el('[data-cancel]').onclick = () => pulse('leave')
  el('[data-rejoin]').onclick = () => { if (!pending) onRejoin() }
  bar.querySelector('[data-stay]').onclick = () => { activity = true; void pulse() }
  bar.querySelector('[data-leave]').onclick = () => pulse('leave')
  void paint(details); timer = repeat(() => { if (state.state !== 'released') void pulse() },5000)
  return { dispose() { disposed = true; abort.abort(); cancel(timer); suspend(); panel.remove(); bar.remove(); if (main) main.inert = false;
    for (const type of ['pointerdown','keydown','wheel']) doc.removeEventListener(type,interacted)
    doc.removeEventListener('visibilitychange',visibility); host?.removeEventListener('pagehide',pagehide) } }
}
