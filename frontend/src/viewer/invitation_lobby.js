/** Wait for an explicitly started presentation without downloading any scene. */
export function mountInvitationLobby({ base, onActive, document: doc = document, fetch: request = fetch, setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  const panel = doc.createElement('section')
  panel.id = 'presentation-waiting'
  panel.style.cssText = 'position:fixed;inset:0;z-index:1000;background:#0d1117;color:#e6edf3;align-content:center;text-align:center;font:16px system-ui'
  panel.innerHTML = '<h1>Presentation not active</h1><p role="status" aria-live="polite">Waiting for the presenter to start. This page will update automatically.</p>'
  const heading = panel.querySelector('h1'), status = panel.querySelector('p'), main = doc.querySelector('main')
  if (main) main.inert = true
  doc.body.append(panel)
  const abort = new AbortController()
  let disposed = false, polling = false, terminal = false
  async function poll() {
    if (disposed || polling || terminal) return
    polling = true
    try {
      const response = await request(`${base}/availability`, { signal: abort.signal })
      if (disposed) return
      if (response.status === 404) {
        terminal = true
        heading.textContent = 'Invitation no longer available'
        status.textContent = 'Ask the presenter for a new link.'
        return
      }
      if (!response.ok) throw new Error('Host unavailable')
      const value = await response.json()
      if (disposed) return
      if (value.state === 'active') { onActive(); return }
      heading.textContent = value.state === 'preparing' ? 'Preparing presentation…' : 'Presentation not active'
      status.textContent = 'Waiting for the presenter to start. This page will update automatically.'
    } catch {
      if (!disposed) {
        heading.textContent = 'Waiting for the host'
        status.textContent = 'The host is currently unreachable. Reconnecting automatically…'
      }
    } finally { polling = false }
  }
  const timer = repeat(poll, 3000)
  void poll()
  return () => { disposed = true; abort.abort(); cancel(timer); panel.remove(); if (main) main.inert = false }
}
