import { createSharedViewMotion } from './shared_view_motion.js'

/** One explicit pose upload; never subscribes to guest camera changes. */
export function mountGuestSharedViews({ parent, viewer, getRevision, ready, beforeMove, onPublished = () => {}, base, document: doc = document, fetch: request = fetch }) {
  const button = doc.createElement('button'); button.type = 'button'; button.dataset.shareView = ''; button.textContent = 'Share view'
  button.title = 'Share your current perspective once. Others can click your glasses icon to view it.'
  const status = doc.createElement('span'); status.setAttribute('role', 'status'); status.dataset.shareViewStatus = ''
  parent.append(button, status)
  const abort = new AbortController()
  let busy = false, disposed = false
  const motion = createSharedViewMotion({ getView: () => {
    if (!ready()) throw new Error('Wait for the shared visualization to finish loading')
    return { camera: viewer.runtime.camera, controls: viewer.runtime.controls, canvas: doc.querySelector('canvas'), context: viewer.current, finish: pose => viewer.applyCamera(pose, 1) }
  } })
  const update = () => { button.disabled = busy || !ready() }
  button.onclick = async () => {
    if (busy || !ready()) return
    busy = true; update(); status.textContent = ''
    try {
      const response = await request(`${base}/share-view`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision: getRevision(), camera: viewer.captureCamera() }), signal: abort.signal })
      if (!response.ok) throw new Error((await response.json()).error || 'Could not share your view')
      if (!disposed) { onPublished(); status.textContent = 'View shared' }
    } catch (error) { if (!disposed) status.textContent = error.message }
    finally { busy = false; if (!disposed) update() }
  }
  return { update, cancel: motion.cancel, move(view) {
    try { beforeMove(); motion.move(view.camera); status.textContent = '' } catch (error) { status.textContent = error.message }
  }, dispose() { disposed = true; abort.abort(); motion.dispose(); button.remove(); status.remove() } }
}
