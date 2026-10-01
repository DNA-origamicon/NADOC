// Progress is measured backend work, not an estimate of remaining wall time.
const active = new Set()
export function cancelSurfaceComputations() { for (const cancel of [...active]) cancel() }

import { showOpProgress, hideOpProgress, updateOpProgress } from '../ui/op_progress.js'

export function isSurfaceComputation(path) {
  return /\/(?:surface(?:-bin|-region|-geometry|-batch|\/region)?|(?:display|rmsf)-surface(?:-bin)?)$/.test(path.split('?')[0])
}

export function surfaceProgressView(value) {
  const group = value.strand ? `Strand ${value.strand.index} of ${value.strand.total} · ` : ''
  if (value.state === 'complete') return { label: 'Receiving surface…', fraction: null }
  const countable = Number.isFinite(value.done) && Number.isFinite(value.total) && value.total > 0
  return {
    label: `${group}${value.stage || 'Preparing surface'}${countable ? ` · ${value.done} / ${value.total}` : ''}`,
    fraction: countable ? Math.max(0, Math.min(1, value.done / value.total)) : null,
  }
}

/** Frozen document headers isolate requests across tab switches. No overlapping polls.
 * The operation owns its token, so an older completion cannot hide a newer popup. */
export async function withSurfaceProgress(path, headers, run, { fetchImpl = fetch, pollMs = 250, signal } = {}) {
  if (!isSurfaceComputation(path)) return run(headers)
  const requestId = crypto.randomUUID?.() ?? Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')
  const controller = new AbortController()
  const cancel = () => {
    if (controller.signal.aborted) return
    controller.abort(new DOMException('Surface computation cancelled', 'AbortError'))
    void fetchImpl(`/api/surface-progress/${requestId}/cancel`, { method: 'POST', headers, keepalive: true }).catch(() => {})
  }
  active.add(cancel)
  signal?.addEventListener('abort', cancel, { once: true })
  if (signal?.aborted) cancel()
  const token = showOpProgress('Computing surface…', 'Preparing atoms', { indeterminate: true, onCancel: cancelSurfaceComputations, detail: 'Progress counts completed work in the current stage' })
  const pollAbort = new AbortController()
  let stopped = false
  let timer = null
  async function poll() {
    try {
      const response = await fetchImpl(`/api/surface-progress/${requestId}`, { headers, signal: pollAbort.signal })
      if (response.ok) {
        const value = await response.json()
        if (!stopped) updateOpProgress(token, surfaceProgressView(value))
      }
    } catch { /* A missed status update must not fail the mesh request. */ }
    if (!stopped) timer = setTimeout(poll, pollMs)
  }
  timer = setTimeout(poll, pollMs)
  try {
    controller.signal.throwIfAborted()
    const result = await run({ ...headers, 'X-NADOC-Surface-Progress': requestId }, controller.signal)
    controller.signal.throwIfAborted()
    return result
  } finally {
    active.delete(cancel)
    signal?.removeEventListener('abort', cancel)
    stopped = true
    clearTimeout(timer)
    pollAbort.abort()
    hideOpProgress(token)
  }
}
