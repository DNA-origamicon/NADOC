/** Serialized into the downloaded HTML. Deliberately has no imports or network access. */
export function offlinePresentation(clips) {
  const stage = document.getElementById('stage'), poster = document.getElementById('poster')
  const status = document.getElementById('status'), jump = document.getElementById('jump')
  let index = 0, video = null, url = null, atEnd = false
  let bridge = null, locked = false, resumePlaying = false
  const notify = (command, state) => { if (bridge) window.parent.postMessage({ type: 'nadoc-compiled', token: bridge, command, state }, '*') }
  window.addEventListener('message', event => {
    if (window.parent === window || event.source !== window.parent || event.data?.type !== 'nadoc-compiled') return
    const message = event.data
    if (message.command === 'connect' && !bridge && typeof message.token === 'string') {
      bridge = message.token
      document.getElementById('fullscreen').hidden = true
      notify('ready'); return
    }
    if (message.token !== bridge || !bridge) return
    if (message.command === 'snapshot' && !locked) {
      resumePlaying = !!video && !video.paused && !atEnd
      const state = { index, time: atEnd ? (clips[index].duration ?? 0) : (video?.currentTime ?? 0), atEnd, playing: resumePlaying }
      video?.pause(); locked = true; label('Preparing live 3D')
      notify('snapshot', state)
    } else if (message.command === 'resume') {
      locked = false
      if (resumePlaying && video && !atEnd) video.play().catch(() => label('Press Play to resume'))
      else label(atEnd ? 'Held' : 'Paused')
    } else if (message.command === 'unlock') { locked = false; label(atEnd ? 'Held' : 'Paused') }
  })
  clips.forEach((clip, i) => jump.add(new Option(`${i + 1}. ${clip.name}`, String(i))))
  function label(message = '') { status.textContent = `${index + 1} / ${clips.length}${message ? ' · ' + message : ''}` }
  function release() {
    if (video) { video.pause(); video.removeAttribute('src'); video.load(); video.remove(); video = null }
    if (url) URL.revokeObjectURL(url)
    url = null
  }
  function show(next, endpoint = false, play = true) {
    if (locked) return
    next = Math.max(0, Math.min(clips.length - 1, next))
    if (next === index && video && !endpoint && play) {
      atEnd = false; video.currentTime = 0
      video.play().catch(() => label('Press Play to start'))
      return
    }
    release()
    index = next; jump.value = String(index)
    const clip = clips[index]
    atEnd = endpoint; poster.src = endpoint ? clip.last : clip.first; poster.hidden = false
    label(endpoint ? 'Held' : 'Ready')
    if (endpoint || !play) return
    const bytes = Uint8Array.from(atob(clip.video.split(',')[1]), c => c.charCodeAt(0))
    url = URL.createObjectURL(new Blob([bytes], { type: 'video/webm' }))
    const current = document.createElement('video'); video = current
    current.muted = true; current.playsInline = true; current.preload = 'auto'
    current.addEventListener('playing', () => { if (video === current) { poster.hidden = true; label('Playing') } })
    current.addEventListener('ended', () => { if (video === current) { atEnd = true; poster.src = clip.last; poster.hidden = false; label('Held') } })
    current.addEventListener('error', () => { if (video === current) label('Video unavailable. Open this file in a browser with WebM support.') })
    stage.prepend(current); current.src = url
    current.play().catch(() => { if (video === current) label('Press Play to start') })
  }
  function next() { if (locked) return; if (index < clips.length - 1) show(index + 1); else { show(index, true); label('End of presentation') } }
  function pause() {
    if (locked) return
    if (!video || atEnd) show(index)
    else if (video.paused) video.play().catch(() => label('Could not play video'))
    else { video.pause(); label('Paused') }
  }
  document.getElementById('back').onclick = () => show(index - 1, true)
  document.getElementById('next').onclick = next
  document.getElementById('replay').onclick = () => show(index)
  document.getElementById('pause').onclick = pause
  document.getElementById('fullscreen').onclick = () => document.documentElement.requestFullscreen?.().catch(() => label('Fullscreen unavailable'))
  jump.onchange = () => show(Number(jump.value))
  stage.onclick = () => { if (!video && !atEnd) show(index); else next() }
  stage.oncontextmenu = e => { e.preventDefault(); show(index - 1, true) }
  document.addEventListener('keydown', e => {
    if (locked && e.key !== 'Escape') { e.preventDefault(); return }
    if (e.target.matches('select,button') && [' ', 'Enter', 'ArrowUp', 'ArrowDown'].includes(e.key)) return
    if (e.repeat) return
    if ([' ', 'ArrowRight', 'ArrowDown', 'PageDown'].includes(e.key)) { e.preventDefault(); if (!video && !atEnd) show(index); else next() }
    else if (['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'].includes(e.key)) { e.preventDefault(); show(index - 1, true) }
    else if (e.key.toLowerCase() === 'r') show(index)
    else if (e.key.toLowerCase() === 'p') pause()
    else if (e.key === 'Escape') { notify('escape'); video?.pause(); label('Paused'); if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {}) }
  })
  window.addEventListener('pagehide', release)
  show(0, false, false)
}
