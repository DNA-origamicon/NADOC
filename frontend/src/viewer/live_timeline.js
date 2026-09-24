/** Small, validated metadata carried atomically with each live render packet. */
export function liveTimeline(value) {
  if (value == null) return null
  if (!Number.isSafeInteger(value.frame) || !Number.isSafeInteger(value.total) || value.frame < 1 || value.total < value.frame || typeof value.playing !== 'boolean') throw new Error('Invalid live trajectory timeline')
  return { frame: value.frame, total: value.total, playing: value.playing }
}
export function mountLiveTimeline(doc) {
  const bar = doc.createElement('div')
  bar.dataset.liveTimeline = ''; bar.hidden = true
  bar.style.cssText = 'position:absolute;bottom:16px;left:50%;transform:translateX(-50%);z-index:10;max-width:calc(100% - 180px);padding:8px 14px;border-radius:8px;background:rgba(24,30,40,.92);color:white'
  bar.innerHTML = '<label style="display:flex;gap:10px;align-items:center;white-space:nowrap"><span data-frame-number></span><input type="range" min="1" value="1" disabled aria-label="Presenter trajectory frame" style="position:static;height:auto;opacity:1;width:clamp(80px,20vw,280px)"><span data-frame-buffering role="status" hidden>Buffering…</span></label>'
  ;(doc.querySelector('main') ?? doc.body).append(bar)
  let displayed = null, waiting = false
  function buffer(value, pending) {
    waiting = value
    bar.querySelector('[data-frame-buffering]').hidden = !waiting
    bar.setAttribute('aria-busy', String(waiting))
    if (!displayed && pending) {
      bar.hidden = false
      bar.querySelector('input').max = String(pending.total)
      bar.querySelector('[data-frame-number]').textContent = `Frame — / ${pending.total}`
    } else bar.hidden = !displayed
  }
  return { setBuffering: buffer, update(value) {
    const timeline = displayed = liveTimeline(value); bar.hidden = !timeline
    if (!timeline) return
    const input = bar.querySelector('input')
    input.max = String(timeline.total); input.value = String(timeline.frame)
    input.setAttribute('aria-valuetext', `Frame ${timeline.frame} of ${timeline.total}`)
    bar.querySelector('[data-frame-number]').textContent = `${timeline.playing ? 'Playing' : 'Paused'} · Frame ${timeline.frame} / ${timeline.total}`
  }, dispose() { bar.remove() } }
}
