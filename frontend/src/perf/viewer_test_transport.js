/** Production benchmark transport. Inert unless the URL explicitly opts in and
 * the local preview server was launched with NADOC_VIEWER_TEST=1. */
export function createViewerTestTransport({ id, location = globalThis.location, EventSource = globalThis.EventSource, fetch = globalThis.fetch } = {}) {
  if (!EventSource || new URLSearchParams(location?.search).get('viewer-test') !== '1') return null
  const handlers = new Map()
  const source = new EventSource(`/__nadoc_viewer_test/browser-events?id=${encodeURIComponent(id)}`)
  let ready
  const connected = new Promise(resolve => { ready = resolve })
  source.onopen = () => { ready(); for (const fn of handlers.get('vite:ws:connect') ?? []) fn() }
  source.onmessage = event => {
    const { event: name, data } = JSON.parse(event.data)
    for (const fn of handlers.get(name) ?? []) fn(data)
  }
  return {
    on(name, fn) { if (!handlers.has(name)) handlers.set(name, new Set()); handlers.get(name).add(fn) },
    off(name, fn) { handlers.get(name)?.delete(fn) },
    async send(event, data) {
      await connected
      const response = await fetch('/__nadoc_viewer_test/browser-message', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: id, event, data }) })
      if (!response.ok) throw new Error(`Viewer test connection failed: ${response.status}`)
    },
    close() { source.close(); handlers.clear() },
  }
}

export function viewerTestDestination(value) {
  const url = new URL(value)
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
      !['5173', '5180', '5181'].includes(url.port) || url.pathname !== '/' || url.username || url.password || url.hash ||
      [...url.searchParams.keys()].some(key => !['doc', 'viewer-test'].includes(key))) throw new Error('Use a loopback benchmark URL on port 5173, 5180, or 5181')
  return url.href
}
