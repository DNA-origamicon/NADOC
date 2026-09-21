/** Camera-only presentation controls. Scientific selection is a separate contract. */
export function mountMeetingPresentation({ viewer, base, role, revision, room, document: doc = document, fetch: request = fetch,
  eventSource = url => new EventSource(url), setInterval: repeat = setInterval, clearInterval: cancel = clearInterval }) {
  const bar = doc.createElement('div'); bar.dataset.presentation = ''; bar.style.cssText = 'display:flex;align-items:center;gap:12px;padding:8px 18px;flex-wrap:wrap'
  bar.innerHTML = role === 'presenter'
    ? '<button data-broadcast aria-pressed="false">Share my perspective</button><span data-connection role="status"></span>'
    : '<button data-jump disabled>Jump to presenter</button><button data-follow aria-pressed="false" disabled>Follow presenter</button><span data-connection role="status"></span>'
  doc.body.insertBefore(bar, doc.querySelector('main'))
  const el = key => bar.querySelector(`[data-${key}]`), status = el('connection'), canvas = doc.querySelector('canvas')
  const frozen = viewer.current, abort = new AbortController(), host = doc.defaultView
  let source
  let disposed = false, connected = false, following = false, savedEnabled = true, broadcasting = false, inFlight = false, latest = null, sequence = -1, sent = '', previousFrame = performance.now()
  let writes = Promise.resolve(), publicationEpoch = 0
  const compatible = () => viewer.current === frozen
  function follow(value) {
    if (value && !following) {
      savedEnabled = viewer.runtime.controls.enabled
      if (latest?.camera) viewer.applyCamera(latest.camera, 1)
      viewer.runtime.controls.enabled = false
    }
    if (!value && following) viewer.runtime.controls.enabled = savedEnabled
    following = value
    el('follow')?.setAttribute('aria-pressed', String(value))
    if (el('follow')) el('follow').textContent = value ? 'Stop following' : 'Follow presenter'
  }
  function update() {
    status.textContent = !compatible() ? 'Different snapshot opened. Reopen the invitation to present.' : !connected ? 'Presentation connection lost; you can still explore.' : role === 'presenter' ? (broadcasting ? 'Your perspective is shared. Guests choose whether to follow.' : 'Your perspective is not being shared.') : following ? 'Following presenter. Drag or scroll to explore independently.' : latest?.presenting ? 'Explore independently, jump once, or follow the presenter.' : 'Presenter is not sharing a perspective.'
    if (el('jump')) el('jump').disabled = !connected || !latest?.camera || !compatible() || viewer.performanceApi.busy
    if (el('follow')) el('follow').disabled = !connected || !latest?.camera || !latest?.presenting || !compatible() || viewer.performanceApi.busy
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
  const lost = () => { connected = false; broadcasting = false; follow(false); update() }
  const receive = event => {
    let value; try { value = JSON.parse(event.data) } catch { return }
    if (value.room !== room || value.revision !== revision || !Number.isSafeInteger(value.sequence) || value.sequence <= sequence) return
    sequence = value.sequence; latest = value
    if (role === 'presenter' && !value.presenting) sent = ''
    if (!value.presenting) follow(false)
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
  connect(); host?.addEventListener('offline', offline); host?.addEventListener('online', online)
  const ownCamera = () => { follow(false); update() }
  for (const type of ['pointerdown', 'wheel', 'dblclick']) canvas.addEventListener(type, ownCamera, { capture: true, passive: true })
  doc.getElementById('reset')?.addEventListener('click', ownCamera, true)
  doc.getElementById('mode')?.addEventListener('change', ownCamera, true)
  if (el('jump')) el('jump').onclick = () => { follow(false); if (latest?.camera) viewer.applyCamera(latest.camera, 1); update() }
  if (el('follow')) el('follow').onclick = () => { follow(!following); previousFrame = performance.now(); update() }
  if (el('broadcast')) el('broadcast').onclick = () => { if (broadcasting) pause(); else { broadcasting = true; publicationEpoch++; sent = ''; update(); void publish() } }
  function frame() {
    if (!compatible()) { follow(false); broadcasting = false; source.close(); update(); return }
    if (following && !viewer.performanceApi.busy && latest?.camera) {
      const time = performance.now(), blend = 1 - Math.exp(-Math.min(100, time - previousFrame) / 70); previousFrame = time
      viewer.applyCamera(latest.camera, blend); viewer.runtime.controls.enabled = false
    }
  }
  // Benchmark orbit owns its camera; do not combine it with follow interpolation.
  const unsubscribe = viewer.performanceApi.subscribe?.(() => { if (viewer.performanceApi.busy) { follow(false); if (broadcasting) pause() }; update() })
  viewer.runtime.addFrameCallback(frame)
  const timer = role === 'presenter' ? repeat(publish, 100) : null
  update()
  return () => {
    if (disposed) return
    disposed = true; follow(false); abort.abort(); disconnect(); unsubscribe?.()
    if (timer !== null) cancel(timer)
    viewer.runtime.removeFrameCallback(frame)
    host?.removeEventListener('offline', offline); host?.removeEventListener('online', online)
    for (const type of ['pointerdown', 'wheel', 'dblclick']) canvas.removeEventListener(type, ownCamera, true)
    doc.getElementById('reset')?.removeEventListener('click', ownCamera, true); doc.getElementById('mode')?.removeEventListener('change', ownCamera, true)
    bar.remove()
  }
}
