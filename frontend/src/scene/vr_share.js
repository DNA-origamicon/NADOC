import { docHeaders } from '../shared/doc_id.js'
/** Remote controls for an existing desktop presentation; never creates a room. */
export function createVRShare({ document: doc = document, request = fetch }) {
  let sending = false, acknowledged = 0
  const bar = () => doc.getElementById('presentation-controls')
  function state() {
    const root = bar(), button = root?.querySelector('.presentation-perspective')
    return { active: !!root && !root.hidden, perspective: button?.getAttribute('aria-pressed') === 'true',
      busy: !!button?.disabled, failed: !!root?.querySelector('.presentation-error')?.textContent, acknowledged }
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
    if (current.active && !current.busy) {
      if (event.action === 'pause' && current.perspective || event.action === 'resume' && !current.perspective)
        root.querySelector('.presentation-perspective')?.click()
      else if (event.action === 'end') root.querySelector('[data-end-presentation]')?.click()
    }
    await publish()
  }
  return { state, publish: () => publish().catch(() => {}), activate, reset() { acknowledged = 0 } }
}
