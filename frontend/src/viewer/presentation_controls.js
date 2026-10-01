import './sharing_controls.css'
import { mountMeetingPresence } from './meeting_presence.js'

/** Persistent controls anchored to the editor's actual 3D canvas area. */
export function initPresentationControls({ document: doc = document, onPerspective, onEnd, onGuestView, onViewLock = async () => {} }) {
  const bar = doc.createElement('div'); bar.id = 'presentation-controls'; bar.hidden = true
  bar.className = 'presentation-controls'; bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Presentation')
  bar.innerHTML = `<span class="presentation-label"><span class="presentation-dot" aria-hidden="true"></span>Presenting</span>
    <button class="btn presentation-perspective" type="button" aria-label="Share perspective" aria-pressed="false" title="Share perspective — let guests follow your camera in the shared view">
      <svg width="22" height="18" viewBox="0 0 24 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 10 4 4h3M22 10l-2-6h-3M9 11c2-2 4-2 6 0"/><rect x="1" y="9" width="8" height="7" rx="3"/><rect x="15" y="9" width="8" height="7" rx="3"/></svg>
    </button><button class="btn presentation-view-lock" type="button" aria-label="Lock guest perspective" aria-pressed="false" title="Lock guest perspective to your camera">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></svg>
    </button><button class="btn btn--danger" type="button" data-end-presentation title="End presentation and close guest access">End</button>
    <span class="presentation-error" role="status" aria-live="polite"></span>`
  ;(doc.getElementById('canvas-area') ?? doc.getElementById('viewport-container') ?? doc.body).append(bar)
  const glasses = bar.querySelector('.presentation-perspective'), end = bar.querySelector('[data-end-presentation]'), error = bar.querySelector('.presentation-error')
  const presence = mountMeetingPresence({ parent: bar, compact: true, onView: onGuestView, document: doc })
  const lock = bar.querySelector('.presentation-view-lock')
  let manualLock = false, animation = false
  let enabled = false, busy = false, disposed = false, generation = 0
  function paint() {
    glasses.setAttribute('aria-pressed', String(enabled))
    glasses.title = enabled ? 'Stop sharing perspective — guests can continue exploring independently' : 'Share perspective — let guests follow your camera in the shared view'
    glasses.setAttribute('aria-label', enabled ? 'Stop sharing perspective' : 'Share perspective')
    glasses.disabled = busy || manualLock || animation; end.disabled = busy
    lock.disabled = busy || animation
    lock.setAttribute('aria-pressed', String(manualLock || animation))
    lock.title = animation ? 'Guest perspective locked during animation' : manualLock ? 'Unlock guest perspective' : 'Lock guest perspective to your camera'
    lock.setAttribute('aria-label', animation ? 'Guest perspective locked during animation' : manualLock ? 'Unlock guest perspective' : 'Lock guest perspective')
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
  lock.onclick = () => act(async () => {
    const next = !manualLock
    await onViewLock(next)
    if (!disposed && !bar.hidden) manualLock = next
  })
  end.onclick = () => act(onEnd)
  return {
    get perspective() { return enabled },
    get viewLocked() { return manualLock || animation },
    get manualViewLock() { return manualLock },
    setAnimation(value) { animation = value; paint() },
    setPerspective(value) { enabled = value; paint() },
    error(message) { error.textContent = message },
    setParticipants: presence.update,
    setActive(active) { bar.hidden = !active; if (!active) { generation++; enabled = false; manualLock = false; animation = false; error.textContent = '' } paint() },
    dispose() { disposed = true; generation++; presence.dispose(); bar.remove() },
  }
}
