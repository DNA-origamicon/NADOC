/** Automatic host startup and public-access wait for the ordinary Create link flow. */
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
  onProgress('Connecting internet sharing…')
  let host = await api('start', { method: 'POST', ...(signal ? { signal } : {}) })
  const deadline = now() + timeoutMs
  while (host.publicAccess && host.publicAccess.state !== 'ready') {
    signal?.throwIfAborted()
    onProgress(host.publicAccess.message)
    if (now() >= deadline) throw new Error('Public access is still unavailable. Hosting will keep checking in the background; try Create link again later.')
    await pause(Math.min(pollMs, Math.max(0, deadline - now())), signal)
    host = await api('status', signal ? { signal } : {})
    if (host.running === false) throw new Error('Hosting stopped before the link was ready. Try Create link again.')
    if (!host.publicAccess) throw new Error('The hosting session changed before verification completed. Try Create link again.')
  }
  signal?.throwIfAborted()
  return host
}
