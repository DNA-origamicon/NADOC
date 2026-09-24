/** Local experience signals, never hardware identity or capacity. */
export function createViewerHealthSignals() {
  let networkSlow = false, renderSlow = false, badNetwork = 0, goodNetwork = 0, badRender = 0, goodRender = 0
  let windowStart = null, frames = 0
  return {
    transfer({ milliseconds, bytes = 0, failed = false }) {
      const slow = failed || (milliseconds > 1500 && (bytes < 65536 || bytes / (milliseconds / 1000) < 128 * 1024))
      if (slow) { badNetwork++; goodNetwork = 0; if (badNetwork >= 2) networkSlow = true }
      else { goodNetwork++; badNetwork = 0; if (goodNetwork >= 3) networkSlow = false }
    },
    frame(time, eligible = true) {
      if (!eligible) { windowStart = null; frames = 0; badRender = goodRender = 0; renderSlow = false; return }
      if (windowStart === null) { windowStart = time; frames = 0; return }
      frames++
      const duration = time - windowStart
      if (duration < 5000) return
      const fps = frames * 1000 / duration
      if (fps < 20) { badRender++; goodRender = 0; if (badRender >= 2) renderSlow = true }
      else if (fps >= 28) { goodRender++; badRender = 0; if (goodRender >= 2) renderSlow = false }
      else { badRender = goodRender = 0 }
      windowStart = time; frames = 0
    },
    snapshot: () => ({ networkSlow, renderSlow }),
  }
}

export function mountViewerHealth({ viewer, base, onChange, document: doc = document, fetch: request = fetch,
  now = () => performance.now(), setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  const signals = createViewerHealthSignals(), abort = new AbortController()
  let active = false, disposed = false, flight = false, signature = ''
  function paint() { const value = signals.snapshot(), next = JSON.stringify(value); if (next !== signature) { signature = next; onChange(value) }; return value }
  const eligible = () => !doc.hidden && !!viewer.current && !viewer.performanceApi?.busy && !doc.querySelector('#meeting-loading:not([hidden])')
  const frame = () => { if (!active || disposed) return; signals.frame(now(), eligible()); paint() }
  viewer.runtime?.addFrameCallback?.(frame)
  async function measuredFetch(url, options) {
    const started = now()
    try {
      const response = await request(url, options)
      if (!response.ok) { if (response.status >= 500) signals.transfer({ milliseconds: now() - started, failed: true }); paint(); return response }
      const isPayload = /\/(scene|frame|live-frame)(?:\?|$)/.test(String(url))
      if (!isPayload) { signals.transfer({ milliseconds: now() - started }); paint(); return response }
      // Observe the existing body read. No clone, extra download, or device query.
      return new Proxy(response, { get(target, key) {
        const value = Reflect.get(target, key, target)
        if (['arrayBuffer', 'blob'].includes(key)) return async (...args) => {
          const body = await value.apply(target, args)
          signals.transfer({ milliseconds: now() - started, bytes: body.byteLength ?? body.size ?? 0 }); paint(); return body
        }
        return typeof value === 'function' ? value.bind(target) : value
      } })
    } catch (error) {
      if (!disposed && !options?.signal?.aborted) { signals.transfer({ milliseconds: now() - started, failed: true }); paint() }
      throw error
    }
  }
  async function report() {
    if (!active || disposed || flight || doc.hidden) return
    flight = true
    try { await request(`${base}/health`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(paint()), signal: abort.signal }) }
    catch { /* Network measurements and connection handling own the visible status. */ }
    finally { flight = false }
  }
  const timer = repeat(report, 10000)
  return { fetch: measuredFetch, start() { if (active) return; active = true; paint(); void report() }, dispose() { disposed = true; active = false; abort.abort(); cancel(timer); viewer.runtime?.removeFrameCallback?.(frame) } }
}
