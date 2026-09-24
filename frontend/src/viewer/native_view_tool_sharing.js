import { broadcastDocument, broadcastFingerprint } from './broadcast_fingerprint.js'

/** Mirror display changes only in the context explicitly published by this editor. */
export function initNativeViewToolSharing({ prepared, store, getContext, getRoom, isBusy, publish, onError,
  setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  let baseline = null, flight = null, epoch = 0, disposed = false
  function capture() {
    const source = prepared.captureView(true)
    return { context: JSON.stringify([broadcastDocument(store.getState()), getContext()]),
      tools: broadcastFingerprint(source), room: getRoom()?.id }
  }
  function remember(value = capture()) { epoch++; baseline = value }
  function clear() { epoch++; baseline = null }
  async function run() {
    if (disposed || !baseline || isBusy()) return
    const next = capture(), ticket = epoch
    const current = () => !disposed && ticket === epoch && !isBusy() && capture().context === next.context && getRoom()?.id === next.room
    if (!next.room || next.room !== baseline.room || next.context !== baseline.context || next.tools === baseline.tools) return
    const result = await prepared.exportView({ presentation: true })
    if (!result || !current()) return
    // A second toggle during preparation will be exported by the next tick.
    if (await publish(result, current) !== false && current()) baseline = next
  }
  function tick() {
    if (!flight) flight = run().catch(error => error.code !== 'VIEW_NOT_READY' && onError(error.message)).finally(() => { flight = null })
    return flight
  }
  const timer = repeat(tick, 1000)
  return { capture, remember, clear, tick, settle: () => flight, dispose() { disposed = true; clear(); cancel(timer) } }
}
