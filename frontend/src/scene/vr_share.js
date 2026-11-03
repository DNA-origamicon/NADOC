import { docHeaders } from '../shared/doc_id.js'
/** VR controls for the shared desktop presentation lifecycle. */
export function createVRShare({ document: doc = document, request = fetch }) {
  let sending = false, acknowledged = 0
  const bar = () => doc.getElementById('presentation-controls')
  function state() {
    const start = doc.getElementById('menu-presentation-start')
    const setupError = doc.getElementById('share-link-dialog')?.querySelector('[data-error]')
    const root = bar(), button = root?.querySelector('.presentation-perspective')
    return { active: !!root && !root.hidden, perspective: button?.getAttribute('aria-pressed') === 'true',
      headsetPerspective: root?.dataset.perspectiveSource === 'headset',
      startAvailable: !!start && !start.disabled,
      busy: doc.getElementById('share-link-dialog')?.getAttribute('aria-busy') === 'true' || !!root?.querySelector('[data-end-presentation]')?.disabled, perspectiveAvailable: !!button && !button.disabled, failed: !!root?.querySelector('.presentation-error')?.textContent || !!setupError && !setupError.hidden && !!setupError.querySelector('[data-error-log]')?.textContent, acknowledged, activeGuests: Number(root?.dataset.activeGuests ?? 0), waitingGuests: Number(root?.dataset.waitingGuests ?? 0) }
  }
  async function publish() {
    if (sending) return
    sending = true
    try { await request('/api/vr/share-controls', { method: 'POST', headers: { ...docHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(state()) }) }
    finally { sending = false }
  }
  async function activate(event) {
    if (!Number.isSafeInteger(event.sequence) || event.sequence <= acknowledged) return
    acknowledged = event.sequence
    const current = state(), root = bar()
    if (event.action === 'start' && !current.active && !current.busy && current.startAvailable) {
      const Event = doc.defaultView?.CustomEvent ?? CustomEvent
      doc.getElementById('menu-presentation-start').dispatchEvent(new Event('click', { detail: { nativeVR: true } }))
    } else if (current.active && !current.busy) {
      if (event.action === 'pause' && current.perspective || event.action === 'resume' && (!current.perspective || !current.headsetPerspective))
        root.querySelector('.presentation-perspective')?.dispatchEvent(new (doc.defaultView?.CustomEvent ?? CustomEvent)('click', { detail: { nativeVR: event.action === 'resume' } }))
      else if (event.action === 'admit') root.querySelector('[data-admit-guests]')?.click()
      else if (event.action === 'end') root.querySelector('[data-end-presentation]')?.click()
    }
    await publish()
  }
  return { state, publish: () => publish().catch(() => {}), activate, reset() { acknowledged = 0 } }
}
