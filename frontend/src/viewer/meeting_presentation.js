import { mountMeetingDrawing } from './meeting_drawing.js'
import { mountViewerScreenshot } from './viewer_screenshot.js'
import { applyAnimationTextOverlay } from '../scene/animation_text_overlay.js'
import { decodeVRUIState } from './vr_ui_stream.js'
import { createVRAvatar } from './vr_avatar.js'
import { createPresenterFollow } from './presenter_follow.js'
import { mountGuestSharedViews } from './guest_shared_views.js'
/** Camera presentation and transient VR presence; scientific selection is separate. */
import { mountMeetingTrajectory } from './meeting_trajectory.js'
import { loadMeetingRevision } from './meeting_scene_updates.js'
import { mountMeetingLiveFrame } from './meeting_live_frame.js'
export function mountMeetingPresentation({ viewer, base, role, revision, room, selfId = '', document: doc = document, fetch: request = fetch,
  eventSource = url => new EventSource(url), loadRevision = loadMeetingRevision, mountTrajectory = mountMeetingTrajectory, onSharedView = () => {}, onEnded = () => {}, onLoading = () => {}, onPresence = () => {}, onViewReady = () => {}, onViewShared = () => {}, setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  const createTrajectory = () => mountTrajectory({ viewer, base, role, document: doc, fetch: request })
  const vrTextures = new Map()
  const avatar = createVRAvatar({ scene: viewer.runtime.scene })
  let trajectory = createTrajectory()
  const createLive = () => mountMeetingLiveFrame({ viewer, base, revision, document: doc, fetch: request, animationEnabled: () => !!latest?.animationActive })
  let live = createLive()
  const bar = doc.createElement('div'); bar.dataset.presentation = ''; bar.style.cssText = 'display:flex;align-items:center;gap:12px;padding:8px 18px;flex-wrap:wrap'
  bar.innerHTML = role === 'presenter'
    ? '<button data-broadcast aria-pressed="false">Share my perspective</button><span data-connection role="status"></span>'
    : '<button data-follow aria-pressed="false" disabled>Follow presenter</button><span data-connection role="status"></span>'
  doc.body.insertBefore(bar, doc.querySelector('main'))
  const el = key => bar.querySelector(`[data-${key}]`), status = el('connection'), canvas = doc.querySelector('canvas')
  let frozen = viewer.current, updating = false, pendingRevision = null, retryAfter = 0
  const abort = new AbortController(), host = doc.defaultView
  let source
  let disposed = false, connected = false, following = false, savedEnabled = true, broadcasting = false, inFlight = false, latest = null, latestAt = 0, sequence = -1, sent = ''
  let writes = Promise.resolve(), publicationEpoch = 0, locked = false, priorFollowing = false
  let drawingActive = false, drawingSavedEnabled = true
  const compatible = () => viewer.current === frozen
  const followMotion = createPresenterFollow({ viewer })
  function follow(value) {
    if (value && !following) {
      savedEnabled = viewer.runtime.controls.enabled
      followMotion.start()
      viewer.runtime.controls.enabled = false
    }
    if (!value && following) { followMotion.stop(); viewer.runtime.controls.enabled = savedEnabled }
    following = value
    el('follow')?.setAttribute('aria-pressed', String(value))
    if (el('follow')) { el('follow').style.background = value ? '#238636' : ''; el('follow').style.borderColor = value ? '#2ea043' : ''; el('follow').style.color = value ? '#fff' : '' }
    if (el('follow')) el('follow').textContent = value ? 'Stop following' : 'Follow presenter'
  }
  const guestViews = role === 'guest' ? mountGuestSharedViews({ parent: bar, viewer, base, document: doc, fetch: request,
    onPublished: onViewShared, getRevision: () => revision, ready: () => !locked && connected && compatible() && !updating && !viewer.performanceApi.busy,
    beforeMove: () => { if (locked) throw new Error('The presenter has locked the perspective'); if (drawingActive) throw new Error('Turn Draw off to change perspective'); follow(false) } }) : null
  const drawing = role === 'guest' ? mountMeetingDrawing({ parent: bar, canvas, viewer, base, selfId, getRevision: () => revision,
    ready: () => connected && compatible() && !updating && !viewer.performanceApi.busy, document: doc, fetch: request,
    onActive: active => {
      if (active) {
        guestViews?.cancel(); follow(false)
        drawingSavedEnabled = viewer.runtime.controls.enabled
        // Clear residual orbit damping once before holding the drawing pose.
        viewer.applyCamera(viewer.captureCamera(), 1)
      }
      drawingActive = active
      viewer.runtime.controls.enabled = active ? false : drawingSavedEnabled
      if (!disposed) update()
    } }) : null
  const screenshot = mountViewerScreenshot({ parent: bar, viewer, canvas, document: doc })
  onViewReady(view => guestViews?.move(view))
  function update() {
    const nextLock = role === 'guest' && connected && compatible() && latest?.viewLocked === true
    // Restore Draw's saved controls before Follow takes ownership of them.
    if (nextLock && drawingActive) drawing?.cancel()
    if (nextLock !== locked) {
      if (nextLock) { priorFollowing = following; guestViews?.cancel(); follow(true) }
      else follow(priorFollowing)
      locked = nextLock
    }
    viewer.setViewLocked?.(locked || drawingActive)
    for (const id of ['reset', 'mode']) { const input = doc.getElementById(id); if (input) input.disabled = locked || drawingActive || !compatible() }
    guestViews?.update(); drawing?.update({ locked })
    onLoading(latest?.loading ?? null, updating)
    status.textContent = !compatible() ? 'Different snapshot opened. Reopen the invitation to present.' : !connected ? 'Presentation connection lost; you can still explore.' : role === 'presenter' ? (broadcasting ? 'Your perspective is shared. Guests choose whether to follow.' : 'Your perspective is not being shared.') : following ? 'Following presenter. Drag or scroll to explore independently.' : latest?.presenting ? 'Explore independently or follow the presenter.' : 'Presenter is not sharing a perspective.'
    if (updating) status.textContent = 'Receiving updated visualizations; your camera stays independent.'
    const canFollow = !updating && latest?.revision === revision && connected && latest?.camera && latest?.presenting && compatible() && !viewer.performanceApi.busy
    if (el('follow')) {
      el('follow').disabled = locked || drawingActive || (!following && !canFollow)
      if (following) {
        viewer.runtime.controls.enabled = locked || canFollow ? false : savedEnabled
        if (!canFollow) status.textContent = 'Following presenter · Waiting for the shared view…'
      }
    }
    if (locked) { status.textContent = latest?.animationActive ? 'Shared animation · Perspective locked by presenter' : 'Perspective locked by presenter'; el('follow').textContent = 'Perspective locked' }
    if (drawingActive) { viewer.runtime.controls.enabled = false; status.textContent = 'Drawing · Camera held steady' }
    if (el('broadcast')) { el('broadcast').disabled = !connected || !compatible() || viewer.performanceApi.busy; el('broadcast').textContent = broadcasting ? 'Pause perspective sharing' : 'Share my perspective'; el('broadcast').setAttribute('aria-pressed', String(broadcasting)) }
  }
  function post(action, body) {
    writes = writes.catch(() => {}).then(async () => {
      const response = await request(`${base}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: abort.signal })
      if (!response.ok) throw new Error((await response.json()).error || 'Presentation update failed')
    })
    return writes
  }
  async function publish() {
    if (disposed || !connected || !broadcasting || inFlight || !compatible() || viewer.performanceApi.busy) return
    const camera = viewer.captureCamera(), encoded = JSON.stringify(camera)
    if (encoded === sent) return
    inFlight = true
    const epoch = publicationEpoch
    try { await post('camera', { revision, camera }); if (epoch === publicationEpoch) sent = encoded }
    catch (error) { if (!disposed) { broadcasting = false; update(); status.textContent = error.message } }
    finally { inFlight = false }
  }
  function pause() { broadcasting = false; publicationEpoch++; sent = ''; void post('pause', {}).catch(() => {}); update() }
  const opened = () => { connected = true; publicationEpoch++; sent = ''; update(); void publish() }
  const lost = () => { avatar.clear(); connected = false; broadcasting = false; follow(false); update() }
  async function refreshScene() {
    if (updating || disposed || !compatible() || performance.now() < retryAfter) return
    updating = true; avatar.clear(); update()
    let failure = null
    try {
      while (pendingRevision && pendingRevision !== revision && !disposed) {
        const next = pendingRevision
        // Finish an in-flight snapshot even if playback has announced a newer one.
        // Otherwise sustained layout changes can starve a slower guest indefinitely.
        const loaded = await loadRevision({ viewer, base, revision: next, fetch: request, signal: abort.signal,
          isCurrent: () => !disposed && pendingRevision !== revision && viewer.current === frozen })
        if (disposed) return
        if (loaded) {
          revision = next; frozen = viewer.current; onSharedView(frozen)
          if (latest?.revision === revision && latest.selectionUpdate?.revision === revision) viewer.receiveSelectionUpdate?.(latest.selectionUpdate)
          if (latest?.revision === revision && latest.selectionPing?.revision === revision) viewer.receiveSelectionPing?.(latest.selectionPing)
          if (latest?.revision === revision) avatar.receive(latest)
          trajectory.dispose(); trajectory = createTrajectory()
          live.dispose(); live = createLive(); if (latest?.revision === revision) live.receive(latest)
          if (latest?.revision === revision) trajectory.receive({ ...latest, serverTime: latest.serverTime + performance.now() - latestAt })
        }
        if (next === pendingRevision && !loaded) break
      }
    } catch (error) { failure = error.message; retryAfter = performance.now() + 3000; follow(false) }
    finally { updating = false; if (!disposed) { update(); if (failure) status.textContent = failure } }
  }
  const receive = event => {
    let value; try { value = JSON.parse(event.data) } catch { return }
    if (value.room !== room || !Number.isSafeInteger(value.sequence) || value.sequence <= sequence) return
    if (value.revision !== revision && !/^[a-f0-9]{64}$/.test(value.revision)) return
    if (!Object.hasOwn(value, 'selectionUpdate') && value.revision === latest?.revision) value.selectionUpdate = latest.selectionUpdate
    try { value = decodeVRUIState(value, vrTextures) } catch { avatar.clear(); return }
    if (value.ended) { avatar.clear(); onEnded(); return }
    onPresence(value.participants ?? [], { serverTime: value.serverTime })
    if (value.revision === revision && compatible()) avatar.receive(value); else avatar.clear()
    sequence = value.sequence; latest = value; latestAt = performance.now(); pendingRevision = value.revision
    if (value.revision === revision && compatible() && value.selectionUpdate?.revision === revision) viewer.receiveSelectionUpdate?.(value.selectionUpdate)
    if (value.revision === revision && compatible() && value.selectionPing?.revision === revision) viewer.receiveSelectionPing?.(value.selectionPing)
    drawing?.receive(value)
    trajectory.receive(value)
    live.receive(value)
    if (!value.animationActive) { const caption = doc.getElementById('anim-text-overlay'); if (caption) applyAnimationTextOverlay(canvas.parentElement, null) }
    if (value.revision !== revision) { broadcasting = false; publicationEpoch++; sent = ''; pendingRevision = value.revision; void refreshScene() }
    if (role === 'presenter' && !value.presenting) sent = ''
    // Keep the guest’s follow preference through scene/lease handoffs.
    // Only explicit guest navigation or loss of the connection cancels it.
    update()
  }
  function connect() {
    source = eventSource(`${base}/events`)
    source.addEventListener('open', opened); source.addEventListener('error', lost); source.addEventListener('state', receive)
  }
  function disconnect() {
    source.removeEventListener('open', opened); source.removeEventListener('error', lost); source.removeEventListener('state', receive); source.close()
  }
  // Browsers can keep a quiet HTTP stream open after the network goes offline.
  const offline = () => { disconnect(); lost() }
  const online = () => { if (!disposed && compatible()) { disconnect(); connect() } }
  const visibility = () => { if (!doc.hidden) online() }
  doc.addEventListener('visibilitychange', visibility)
  connect(); host?.addEventListener('offline', offline); host?.addEventListener('online', online)
  const ownCamera = () => { if (locked || drawingActive) return; guestViews?.cancel(); follow(false); update() }
  for (const type of ['pointerdown', 'wheel', 'dblclick', 'nadoc:view-navigation']) canvas.addEventListener(type, ownCamera, { capture: true, passive: true })
  doc.getElementById('reset')?.addEventListener('click', ownCamera, true)
  doc.getElementById('mode')?.addEventListener('change', ownCamera, true)
  if (el('follow')) el('follow').onclick = () => { if (locked || drawingActive) return; guestViews?.cancel(); follow(!following); update() }
  if (el('broadcast')) el('broadcast').onclick = () => { if (broadcasting) pause(); else { broadcasting = true; publicationEpoch++; sent = ''; update(); void publish() } }
  function frame() {
    if (compatible() && !updating) avatar.frame(); else avatar.clear()
    if (updating) return
    if (!compatible()) { follow(false); broadcasting = false; source.close(); update(); return }
    if (following && connected && latest?.presenting && latest?.revision === revision && !viewer.performanceApi.busy && latest?.camera) {
      if (!latest.animationActive) followMotion.frame(latest.camera)
      viewer.runtime.controls.enabled = false
    }
  }
  // Benchmark orbit owns its camera; do not combine it with follow interpolation.
  const unsubscribe = viewer.performanceApi.subscribe?.(() => { if (viewer.performanceApi.busy) { follow(false); if (broadcasting) pause() }; update() })
  viewer.runtime.addFrameCallback(frame)
  const timer = repeat(() => { if (pendingRevision && pendingRevision !== revision) void refreshScene(); else if (role === 'presenter') return publish() }, role === 'presenter' ? 100 : 1000)
  update()
  return () => {
    if (disposed) return
    disposed = true; drawing?.dispose(); screenshot.dispose(); viewer.setViewLocked?.(false); if (doc.getElementById('anim-text-overlay')) applyAnimationTextOverlay(canvas.parentElement, null); vrTextures.clear(); avatar.dispose(); guestViews?.dispose(); onViewReady(() => {}); trajectory.dispose(); live.dispose(); follow(false); abort.abort(); disconnect(); unsubscribe?.()
    if (timer !== null) cancel(timer)
    viewer.runtime.removeFrameCallback(frame)
    doc.removeEventListener('visibilitychange', visibility)
    host?.removeEventListener('offline', offline); host?.removeEventListener('online', online)
    for (const type of ['pointerdown', 'wheel', 'dblclick', 'nadoc:view-navigation']) canvas.removeEventListener(type, ownCamera, true)
    doc.getElementById('reset')?.removeEventListener('click', ownCamera, true); doc.getElementById('mode')?.removeEventListener('change', ownCamera, true)
    bar.remove()
  }
}
