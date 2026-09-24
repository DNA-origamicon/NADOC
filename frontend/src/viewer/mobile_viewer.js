/** Touch policy for the standalone viewer, independent of presenter navigation. */
export function isTouchViewer(host = window) {
  return !!host.matchMedia?.('(pointer: coarse)').matches
}

export function mountMobileViewer({ viewer, document: doc = document }) {
  if (!viewer.mobile) return () => {}
  const host = doc.defaultView, body = doc.body, canvas = doc.querySelector('canvas')
  body.classList.add('mobile-viewer')
  const help = doc.createElement('button')
  help.textContent = 'Help'; help.setAttribute('aria-expanded', 'false')
  help.onclick = () => {
    const open = body.classList.toggle('mobile-details')
    help.setAttribute('aria-expanded', String(open))
  }
  const center = doc.createElement('button')
  center.textContent = 'Center'; center.setAttribute('aria-pressed', 'false')
  center.title = 'Choose a new rotation center by tapping the design'
  let armed = false, gesture = null
  const arm = value => { armed = value; gesture = null; center.textContent = value ? 'Tap design' : 'Center'; center.setAttribute('aria-pressed', String(value)) }
  center.onclick = () => arm(!armed)
  const down = event => {
    if (!armed) return
    if (gesture) gesture.cancelled = true
    else gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, cancelled: false }
  }
  const move = event => {
    if (gesture && Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 8) gesture.cancelled = true
  }
  const up = event => {
    if (gesture?.id !== event.pointerId) return
    const tap = !gesture.cancelled; gesture = null
    if (armed && tap && viewer.centerAt(event)) arm(false)
  }
  const cancel = () => { gesture = null }
  canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointermove', move)
  canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', cancel)
  doc.querySelector('header').append(center, help)
  const notice = doc.createElement('aside')
  notice.className = 'mobile-landscape'; notice.hidden = true
  notice.innerHTML = '<strong>Rotate your phone for a wider view</strong><p>One finger rotates. Pinch to zoom; drag with two fingers to pan.</p><button data-fullscreen>Open landscape view</button> <button data-dismiss>Continue in portrait</button><p data-orientation-status role="status"></p>'
  doc.querySelector('main').append(notice)
  let dismissed = false, disposed = false
  const update = () => { notice.hidden = dismissed || !viewer.current || !!doc.querySelector('#join[open]') || host.innerWidth >= host.innerHeight }
  notice.querySelector('[data-dismiss]').onclick = () => { dismissed = true; update() }
  notice.querySelector('[data-fullscreen]').onclick = async () => {
    try {
      if (!doc.fullscreenElement) await doc.documentElement.requestFullscreen?.()
      await host.screen.orientation?.lock?.('landscape')
    } catch { /* Safari and embedded browsers may require physical rotation. */ }
    if (!disposed) {
      update()
      notice.querySelector('[data-orientation-status]').textContent = 'If your screen stays upright, rotate your phone and turn off its rotation lock.'
    }
  }
  const recovery = doc.createElement('div')
  recovery.className = 'mobile-recovery'; recovery.hidden = true; recovery.setAttribute('role', 'status')
  recovery.textContent = 'Graphics interrupted. Waiting for the browser to recover… If this persists, reload the invitation.'
  doc.querySelector('main').append(recovery)
  const lost = event => { event.preventDefault(); recovery.hidden = false }
  const restored = () => { recovery.hidden = true }
  canvas.addEventListener('webglcontextlost', lost)
  canvas.addEventListener('webglcontextrestored', restored)
  const observer = new host.MutationObserver(update)
  observer.observe(doc.getElementById('join'), { attributes: true, attributeFilter: ['open'] })
  observer.observe(doc.getElementById('title'), { childList: true })
  host.addEventListener('resize', update)
  update()
  return () => {
    disposed = true; observer.disconnect(); host.removeEventListener('resize', update)
    canvas.removeEventListener('webglcontextlost', lost); canvas.removeEventListener('webglcontextrestored', restored)
    canvas.removeEventListener('pointerdown', down); canvas.removeEventListener('pointermove', move)
    canvas.removeEventListener('pointerup', up); canvas.removeEventListener('pointercancel', cancel)
    center.remove(); help.remove(); notice.remove(); recovery.remove(); body.classList.remove('mobile-viewer', 'mobile-details')
  }
}
