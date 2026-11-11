import './animation_presentation.css'

/** Local, manually advanced presentation. The existing player owns all scene state. */
export function initAnimationPresentation({ host, viewport, player, getAnimation, isPart,
  stopPreview, onError, document: doc = document, window: win = window }) {
  const button = doc.createElement('button')
  button.id = 'anim-start-presentation-btn'
  button.className = 'btn btn--danger btn--block animation-presentation-start'
  button.textContent = 'Start Presentation'
  button.title = 'Present this animation: click / Space / arrows to navigate; Esc to exit'
  host?.prepend(button)
  let active = false, ready = false, generation = 0, frame = null
  let ends = [], index = 0, moving = false, saved = null, previousFocus = null
  let enteredFullscreen = false, startingPlayer = false

  function refresh() {
    button.hidden = !isPart()
    button.disabled = active || !getAnimation()?.keyframes?.length
  }

  function exit(stopPlayer = true) {
    if (!active) return
    active = false
    ready = false
    generation++
    if (frame !== null) win.cancelAnimationFrame(frame)
    frame = null
    viewport.classList.remove('animation-presentation-active')
    doc.body.classList.remove('animation-presentation-mode')
    if (stopPlayer) player.stop()
    player.setBounce(saved.bounce)
    player.setLoopMode(saved.loop)
    player.setDisablePoses(saved.disablePoses)
    if (enteredFullscreen && doc.fullscreenElement === viewport) {
      Promise.resolve(doc.exitFullscreen()).catch(() => {})
    }
    enteredFullscreen = false
    win.dispatchEvent(new win.Event('resize'))
    previousFocus?.focus?.({ preventScroll: true })
    refresh()
  }

  // Seek serially and wait for the player's representation/trajectory work before
  // scheduling another frame. Rendering time is excluded from animation time.
  async function moveTo(next, { jump = false, from = null } = {}) {
    index = next
    moving = true
    const token = ++generation
    if (frame !== null) win.cancelAnimationFrame(frame)
    frame = null
    let time = from ?? player.getCurrentTime()
    const target = ends[index]
    // Interrupt the old seek loop immediately. Forward skips its remaining
    // transition/hold; backward applies the previous endpoint without playback.
    if (jump || from !== null) {
      time = jump ? target : from
      try {
        player.seekTo(time)
        await player.settleFrame()
      } catch (error) {
        if (active && token === generation) { exit(); onError(error) }
        return
      }
      if (!active || token !== generation) return
      if (jump) { moving = false; return }
    }
    const direction = target >= time ? 1 : -1
    let last = win.performance.now()
    async function tick(now) {
      if (!active || token !== generation) return
      time += direction * Math.max(0, now - last) / 1000
      time = direction > 0 ? Math.min(time, target) : Math.max(time, target)
      try {
        player.seekTo(time)
        await player.settleFrame()
      } catch (error) {
        if (token === generation) { exit(); onError(error) }
        return
      }
      if (!active || token !== generation) return
      if (time === target) {
        moving = false
        frame = null
        if (index === ends.length - 1) exit()
      } else {
        last = win.performance.now()
        frame = win.requestAnimationFrame(tick)
      }
    }
    frame = win.requestAnimationFrame(tick)
  }

  function navigate(direction) {
    if (!ready) return
    if (direction < 0) void moveTo(Math.max(0, index - 1), { jump: true })
    else if (index === ends.length - 1) exit()
    else void moveTo(index + 1, { from: moving ? ends[index] : null })
  }

  async function start() {
    const source = getAnimation()
    if (active || !isPart() || !viewport || !source?.keyframes?.length) return
    stopPreview()
    saved = { bounce: player.getBounce(), loop: player.getLoopMode(), disablePoses: player.getDisablePoses() }
    previousFocus = doc.activeElement
    active = true
    ready = false
    enteredFullscreen = false
    const token = ++generation
    refresh()
    viewport.classList.add('animation-presentation-active')
    doc.body.classList.add('animation-presentation-mode')
    win.dispatchEvent(new win.Event('resize'))
    // Request synchronously in the button gesture, before any asynchronous bake.
    let fullscreen
    try { fullscreen = viewport.requestFullscreen?.() } catch { /* viewport fallback */ }
    Promise.resolve(fullscreen).then(() => {
      if (doc.fullscreenElement !== viewport) return
      if (!active) { void doc.exitFullscreen()?.catch(() => {}); return }
      enteredFullscreen = true
    }).catch(() => { /* Fixed viewport remains available if fullscreen is denied. */ })
    // Give zero-duration cuts distinct endpoints without changing the saved animation.
    const animation = { ...source, loop: false, keyframes: source.keyframes.map(kf => ({
      ...kf, transition_duration_s: Math.max(0, Number(kf.transition_duration_s) || 0),
      hold_duration_s: Math.max(0.001, Number(kf.hold_duration_s) || 0),
    })) }
    let end = 0
    ends = animation.keyframes.map(kf => (end += kf.transition_duration_s + kf.hold_duration_s))
    player.setBounce(false)
    player.setDisablePoses(false)
    try {
      startingPlayer = true
      const preparation = player.play(animation, { holdKeyframeText: true })
      startingPlayer = false
      await preparation
      if (!active || token !== generation) return
      player.pause()
      ready = true
      moveTo(0)
    } catch (error) {
      startingPlayer = false
      if (active && token === generation) { exit(); onError(error) }
    }
  }

  function keydown(event) {
    if (!active) return
    event.preventDefault()
    event.stopImmediatePropagation()
    if (event.key === 'Escape') exit()
    else if (!event.repeat && [' ', 'ArrowRight', 'ArrowDown', 'PageDown'].includes(event.key)) navigate(1)
    else if (!event.repeat && ['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'].includes(event.key)) navigate(-1)
  }
  function pointer(event) {
    if (!active) return
    event.preventDefault()
    event.stopImmediatePropagation()
    if (event.type === 'click') navigate(1)
    else if (event.type === 'contextmenu') navigate(-1)
  }
  function fullscreenChange() {
    if (active && enteredFullscreen && doc.fullscreenElement !== viewport) exit()
  }
  button.addEventListener('click', start)
  win.addEventListener('keydown', keydown, true)
  const pointerEvents = ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click', 'dblclick', 'contextmenu', 'wheel']
  for (const type of pointerEvents) viewport?.addEventListener(type, pointer, { capture: true, passive: false })
  doc.addEventListener('fullscreenchange', fullscreenChange)
  refresh()
  return { start, exit, refresh,
    onPlayerEvent(event) {
      if (active && !startingPlayer && event.type === 'stopped') exit(false)
      else if (active && ['baking_cancelled', 'baking_error'].includes(event.type)) exit()
    },
    dispose() {
      exit()
      button.remove()
      win.removeEventListener('keydown', keydown, true)
      for (const type of pointerEvents) viewport?.removeEventListener(type, pointer, true)
      doc.removeEventListener('fullscreenchange', fullscreenChange)
    },
  }
}
