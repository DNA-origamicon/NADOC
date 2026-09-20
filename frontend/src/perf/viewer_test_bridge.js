import { createViewerTestTransport, viewerTestDestination } from './viewer_test_transport.js'

/** Small browser adapter; timed runs reuse the exact manual capture implementation. */
export function connectViewerTestBridge({ hot, api, snapshot, inspect, openFile, document: doc = document }) {
  const id = crypto.randomUUID()
  if (!hot || typeof hot.off !== 'function') hot = createViewerTestTransport({ id })
  if (!hot) return () => {}
  let active = false, disposed = false, unsubscribe = null
  const register = () => hot.send('nadoc:viewer-register', { id, status: inspect() })
  const send = value => { if (!disposed) return hot.send('nadoc:viewer-result', value) }
  async function command(request) {
    if (active) { send({ id: request.id, error: 'Viewer command already running' }); return }
    active = true
    try {
      if (request.action === 'inspect') send({ id: request.id, result: inspect() })
      else {
        if (doc.hidden) throw new Error('Keep the viewer tab visible and the window unminimized')
        if (api.busy) throw new Error('A manual capture is already running')
        if (doc.querySelector('#process-log')) throw new Error('Close Process Log before automated capture or snapshots')
        if (request.action === 'visit') {
          const url = viewerTestDestination(request.options.url)
          if (new URL(url).hostname !== location.hostname) throw new Error('Keep the same browser hostname when switching builds')
          await fetch(url, { mode: 'no-cors', cache: 'no-store', signal: AbortSignal.timeout(5000) })
          await send({ id: request.id, result: { navigating_to: url } })
          setTimeout(() => { if (!disposed) location.assign(url) }, 300)
        }
        else if (request.action === 'open') {
          const started = performance.now()
          await openFile(request.options.path)
          send({ id: request.id, result: { ...inspect(), file_load: { path: request.options.path,
            elapsed_ms: performance.now() - started, measurement: 'Normal file-open workflow completion; auxiliary assets may continue settling' } } })
        }
        else if (request.action === 'snapshot') send({ id: request.id, result: await snapshot() })
        else if (request.action === 'capture') {
          await new Promise((resolve, reject) => {
            let started = false
            unsubscribe = api.subscribe(() => {
              if (started && !api.busy && api.latest) { unsubscribe(); unsubscribe = null; resolve() }
            })
            api.start(request.options).then(() => { started = true }).catch(reject)
          })
          send({ id: request.id, result: { metrics: api.latest, after: inspect() } })
        } else throw new Error('Unsupported viewer command')
      }
    } catch (error) { send({ id: request.id, error: error.message }) }
    finally { unsubscribe?.(); unsubscribe = null; active = false }
  }
  hot.on('nadoc:viewer-command', command)
  hot.on('vite:ws:connect', register)
  register()
  return () => {
    disposed = true
    unsubscribe?.()
    hot.off('nadoc:viewer-command', command)
    hot.off('vite:ws:connect', register)
    hot.close?.()
  }
}
