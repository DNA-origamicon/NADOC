import { broadcastDocument, broadcastFingerprint } from './broadcast_fingerprint.js'

/** Mirror completed design/display changes only in the explicitly published context. */
export function initNativeViewToolSharing({ prepared, store, getContext, getRoom, isBusy, publish, onError,
  setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  let baseline = null, pending = null, flight = null, epoch = 0, disposed = false
  function capture() {
    const source = prepared.captureView(true), state = store.getState()
    return { context: JSON.stringify([broadcastDocument(state), getContext()]),
      design: state.currentDesign, assembly: state.currentAssembly,
      geometry: state.currentGeometry, axes: state.currentHelixAxes,
      structure: broadcastFingerprint(source, { coordinates: false }),
      tools: broadcastFingerprint(source), room: getRoom()?.id }
  }
  const sameDesign = (a, b) => a && b && ['design', 'assembly', 'geometry', 'axes'].every(key => a[key] === b[key])
  const same = (a, b) => sameDesign(a, b) && a.tools === b.tools && a.context === b.context && a.room === b.room
  const stable = (a, b) => sameDesign(a, b) && a.structure === b.structure && a.context === b.context && a.room === b.room
  function remember(value = capture()) { epoch++; baseline = value; pending = null }
  function clear() { epoch++; baseline = pending = null }
  async function run() {
    if (disposed || !baseline || isBusy()) return
    const next = capture(), ticket = epoch
    const current = () => !disposed && ticket === epoch && !isBusy() && stable(capture(), next)
    if (!next.room || next.room !== baseline.room || next.context !== baseline.context) { pending = null; return }
    if (same(next, baseline)) return
    // Topology and derived geometry can arrive separately. Keep the last complete
    // guest scene until the new design/display is unchanged across polling ticks.
    if (!sameDesign(next, baseline) && !stable(next, pending)) { pending = next; return }
    const result = await prepared.exportView({ presentation: true })
    if (!result || !current()) return
    if (await publish(result, current) !== false && current()) { baseline = next; pending = null }
  }
  function tick() {
    if (!flight) flight = run().catch(error => error.code !== 'VIEW_NOT_READY' && onError(error.message)).finally(() => { flight = null })
    return flight
  }
  const timer = repeat(tick, 1000)
  return { capture, remember, clear, tick, settle: () => flight, dispose() { disposed = true; clear(); cancel(timer) } }
}
