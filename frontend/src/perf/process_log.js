/** Lightweight session diagnostics. Never retain request bodies or design objects. */
export const PROCESS_LOG_LIMIT = 2000
const entries = new Map()
let discarded = 0
export function recordProcess(key, update) {
  const previous = entries.get(key)
  entries.set(key, { key, startedAt: performance.now(), startedWall: Date.now(), status: 'Running', ...previous, ...update })
  while (entries.size > PROCESS_LOG_LIMIT) {
    // Prefer evicting completed work so long-running requests remain visible.
    const candidate = [...entries].find(([, value]) => value.status !== 'Running')
    entries.delete(candidate?.[0] ?? entries.keys().next().value)
    discarded++
  }
}
export function recordRequestDiagnostic(detail) {
  if (!['start', 'complete', 'error', 'aborted'].includes(detail.phase)) return
  const { id, method, path, phase, durationMs, networkMs, status, message, serverTiming } = detail
  recordProcess(`request:${id}`, {
    label: `${method} ${path}`, kind: 'API request',
    status: phase === 'start' ? 'Running' : phase === 'aborted' ? 'Cancelled' : phase === 'error' || status >= 400 ? 'Failed' : 'Completed',
    ...(durationMs === undefined ? {} : { durationMs }),
    ...(phase === 'start' ? {} : { detail: [
      status ? `HTTP ${status}` : '', message,
      networkMs === undefined ? '' : `Response headers: ${networkMs.toFixed(1)} ms; body / parse: ${Math.max(0, durationMs - networkMs).toFixed(1)} ms`,
      serverTiming ? `Server timing: ${serverTiming}` : '',
    ].filter(Boolean).join('\n') }),
  })
}
export function processLogSnapshot() { return { entries: [...entries.values()], discarded } }
export function clearProcessLog() {
  for (const [key, entry] of entries) if (entry.status !== 'Running') entries.delete(key)
  discarded = 0
}
