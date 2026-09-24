import './sharing_controls.css'
import { mountMeetingPresence } from './meeting_presence.js'

/** Persistent controls anchored to the editor's actual 3D canvas area. */
export function initPresentationControls({ document: doc = document, onPerspective, onEnd, onGuestView }) {
  const bar = doc.createElement('div'); bar.id = 'presentation-controls'; bar.hidden = true
  bar.className = 'presentation-controls'; bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Presentation')
  bar.innerHTML = `<span class="presentation-label"><span class="presentation-dot" aria-hidden="true"></span>Presenting</span>
    <button class="btn presentation-perspective" type="button" aria-label="Share perspective" aria-pressed="false" title="Share perspective — let guests follow your camera in the shared view">
      <svg width="22" height="18" viewBox="0 0 24 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 10 4 4h3M22 10l-2-6h-3M9 11c2-2 4-2 6 0"/><rect x="1" y="9" width="8" height="7" rx="3"/><rect x="15" y="9" width="8" height="7" rx="3"/></svg>
    </button><button class="btn btn--danger" type="button" data-end-presentation title="End presentation and stop hosting all links">End</button>
    <span class="presentation-error" role="status" aria-live="polite"></span>`
  ;(doc.getElementById('canvas-area') ?? doc.getElementById('viewport-container') ?? doc.body).append(bar)
  const glasses = bar.querySelector('.presentation-perspective'), end = bar.querySelector('[data-end-presentation]'), error = bar.querySelector('.presentation-error')
  const presence = mountMeetingPresence({ parent: bar, compact: true, onView: onGuestView, document: doc })
  let enabled = false, busy = false, disposed = false, generation = 0
  function paint() {
    glasses.setAttribute('aria-pressed', String(enabled))
    glasses.title = enabled ? 'Stop sharing perspective — guests can continue exploring independently' : 'Share perspective — let guests follow your camera in the shared view'
    glasses.setAttribute('aria-label', enabled ? 'Stop sharing perspective' : 'Share perspective')
    glasses.disabled = busy; end.disabled = busy
  }
  async function act(action) {
    if (busy || disposed) return
    busy = true; error.textContent = ''; const ticket = generation; paint()
    try { await action() } catch (reason) { if (!disposed && ticket === generation) error.textContent = reason.message }
    finally { busy = false; if (!disposed) paint() }
  }
  glasses.onclick = () => act(async () => {
    const next = !enabled
    await onPerspective(next)
    if (!disposed && !bar.hidden) enabled = next
  })
  end.onclick = () => act(onEnd)
  return {
    get perspective() { return enabled },
    setPerspective(value) { enabled = value; paint() },
    error(message) { error.textContent = message },
    setParticipants: presence.update,
    setActive(active) { bar.hidden = !active; if (!active) { generation++; enabled = false; error.textContent = '' } paint() },
    dispose() { disposed = true; generation++; presence.dispose(); bar.remove() },
  }
}
