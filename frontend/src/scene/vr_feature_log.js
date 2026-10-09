import { docHeaders } from '../shared/doc_id.js'
const wire = state => JSON.parse(JSON.stringify(state, (key, value) => ['element', 'actions', 'value'].includes(key) ? undefined : value))

/** Revision-checked commands; existing desktop handlers retain all safeguards. */
export function createVRFeatureLog({ panel, store, refresh, request = fetch, onError = console.error }) {
  let version = 1, acknowledged = 0, published, sending = false, epoch = 0, activeUntil = 0
  let watching = false, refreshing = false, dirty = false, status = '', refreshTimer
  const pending = new Set(), win = globalThis.window
  const diagnostic = ({ detail: event }) => {
    if (event.phase === 'start' && watching && Date.now() <= activeUntil && event.method !== 'GET' && /^\/(design|assembly)\//.test(event.path)) pending.add(event.id)
    if (['complete', 'error'].includes(event.phase) && pending.delete(event.id) && (event.phase === 'error' || event.status >= 400)) status = event.message || 'History operation failed'
  }
  win?.addEventListener('nadoc:api-request', diagnostic)
  async function refreshScene() {
    if (refreshing) { dirty = true;return }
    refreshing = true
    const generation = epoch
    try { do { dirty = false;const result = await refresh();if (!result?.published) throw new Error('History changed, but VR scene refresh failed') } while (dirty && generation === epoch) }
    catch (error) { if (generation === epoch) { status = error.message;onError(status) } }
    finally { refreshing = false;if (generation === epoch) void publish() }
  }
  const unsubscribe = store.subscribe((next, previous) => {
    if (!watching || Date.now() > activeUntil || (next.currentDesign === previous.currentDesign && next.currentAssembly === previous.currentAssembly)) return
    clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => { void refreshScene() }, 120)
  })
  function snapshot() {
    const state = panel().vr.snapshot()
    return { ...state, busy: state.busy || refreshing || pending.size > 0, status: status || state.status || (refreshing ? 'Updating VR scene' : 'Drag rail, release to load state') }
  }
  async function publish() {
    activeUntil = Date.now() + 1500
    if (sending) return
    const state = snapshot(), data = wire(state), signature = JSON.stringify(data)
    if (published?.signature === signature && published.acknowledged === acknowledged) return
    const current = ++version, generation = epoch, ack = acknowledged
    sending = true
    try {
      const response = await request('/api/vr/feature-log', { method: 'POST', headers: { ...docHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ ...data, version: current, acknowledged: ack }) })
      if (!response.ok) throw new Error('Could not update VR feature log')
      if (generation === epoch) published = { state, signature, version: current, acknowledged: ack }
    } finally { sending = false }
  }
  async function activate(event) {
    if (!Number.isSafeInteger(event.sequence) || event.sequence <= acknowledged) return
    acknowledged = event.sequence
    const state = snapshot()
    if (!published || event.version !== published.version || JSON.stringify(wire(state)) !== published.signature || state.busy) { await publish();return }
    status = '';watching = true
    await panel().vr.activate(event.id, state)
    await publish()
  }
  return { snapshot: () => wire(snapshot()), publish: () => publish().catch(() => {}), activate: event => activate(event).catch(error => { status = error.message;onError(status) }),
    reset() { epoch++;acknowledged = 0;published = null;activeUntil = 0;watching = false;status = '';dirty = false;pending.clear();clearTimeout(refreshTimer) },
    dispose() { unsubscribe?.();clearTimeout(refreshTimer);win?.removeEventListener('nadoc:api-request', diagnostic) } }
}
