/** Automatic host startup and public-access wait for the ordinary Enable link flow. */
function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    signal?.throwIfAborted()
    const aborted = () => { clearTimeout(timer); reject(signal.reason) }
    const timer = setTimeout(() => { signal?.removeEventListener('abort', aborted); resolve() }, ms)
    signal?.addEventListener('abort', aborted, { once: true })
  })
}
export async function waitForPublicHosting({ api, onProgress = () => {}, signal, timeoutMs = 15 * 60 * 1000, pollMs = 3000, now = Date.now }) {
  signal?.throwIfAborted()
  const deadline = now() + timeoutMs
  const controller = new AbortController()
  const cancel = () => controller.abort(signal.reason)
  signal?.addEventListener('abort', cancel, { once: true })
  const expired = () => controller.abort(new Error('Public access is still unavailable. Hosting will keep checking in the background; try Enable link again later.'))
  const timer = setTimeout(expired, timeoutMs)
  const pendingSignal = controller.signal
  let aborted
  const cancellation = new Promise((_, reject) => {
    aborted = () => reject(pendingSignal.reason)
    pendingSignal.addEventListener('abort', aborted, { once: true })
  })
  const connect = async () => {
    onProgress('Connecting internet sharing…')
    let host = await api('start', { method: 'POST', signal: pendingSignal })
    while (host.publicAccess && host.publicAccess.state !== 'ready') {
      pendingSignal.throwIfAborted()
      onProgress(host.publicAccess.message || 'Checking public DNS and HTTPS…')
      if (now() >= deadline) { expired(); pendingSignal.throwIfAborted() }
      await pause(Math.min(pollMs, Math.max(0, deadline - now())), pendingSignal)
      host = await api('status', { signal: pendingSignal })
      if (host.running === false) throw new Error('Hosting stopped before the link was ready. Try Enable link again.')
      if (!host.publicAccess) throw new Error('The hosting session changed before verification completed. Try Enable link again.')
    }
    pendingSignal.throwIfAborted()
    return host
  }
  try {
    // Bound even a stalled start/status request, including transports that do
    // not honor AbortSignal. A late response cannot finish a canceled attempt.
    return await Promise.race([connect(), cancellation])
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', cancel)
    pendingSignal.removeEventListener('abort', aborted)
  }
}
