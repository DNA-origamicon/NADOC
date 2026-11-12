import { createCompiledInspection } from './compiled_inspection.js'

/** In-app video shell. Only this shell may hand ownership back to live 3D. */
export function initCompiledPresentationPlayer({ viewport, player, camera, controls, captureCamera, isCurrent, sameDocument, getPlayOptions, beforeStart }) {
  let shell = null, frame = null, status = null, action = null, current = null, token = null
  let mode = 'video', generation = 0, restoreFullscreen = false
  const applyCamera = pose => {
    if (!pose) return
    camera.position.fromArray(pose.position); camera.up.fromArray(pose.up)
    controls.target.fromArray(pose.target); camera.fov = pose.fov
    camera.updateProjectionMatrix(); controls.update()
  }
  const inspection = createCompiledInspection({ player, captureCamera, applyCamera, isCurrent, sameDocument, getPlayOptions })
  const send = command => frame?.contentWindow?.postMessage({ type: 'nadoc-compiled', token, command }, '*')
  function close() {
    generation++; inspection.release()
    if (shell && document.fullscreenElement === viewport) void document.exitFullscreen()?.catch(() => {})
    shell?.remove(); shell = frame = null; current = null; token = null
    mode = 'video'; restoreFullscreen = false
  }
  function resume() {
    generation++; inspection.release()
    mode = 'video'; shell.classList.remove('compiled-live-inspection'); frame.hidden = false
    action.textContent = 'Inspect in 3D'; action.disabled = false; status.textContent = ''
    shell.querySelector('.compiled-cancel').hidden = true
    if (restoreFullscreen) { restoreFullscreen = false; void viewport.requestFullscreen?.().catch(() => {}) }
    send('resume'); frame.focus()
  }
  async function inspect(state) {
    if (!shell || mode !== 'video') return
    mode = 'preparing'
    const run = ++generation
    action.disabled = true
    status.textContent = 'Preparing live 3D… The video stays paused until the frame is ready.'
    shell.querySelector('.compiled-cancel').hidden = false
    // Freeze clip navigation too, so the eventual 3D frame always matches its video.
    frame.style.pointerEvents = 'none'; shell.querySelector('.compiled-cancel').focus()
    try {
      const ready = await inspection.inspect(current, state)
      if (!shell || run !== generation) return
      if (!ready) throw new Error('Live preparation was interrupted.')
      mode = 'inspection'; shell.classList.add('compiled-live-inspection'); frame.hidden = true
      action.textContent = 'Return to presentation'; action.disabled = false
      shell.querySelector('.compiled-cancel').hidden = true
      status.textContent = 'Live 3D · orbit, zoom, or use the app. Your presentation position is saved.'
      if (document.fullscreenElement === viewport) {
        restoreFullscreen = true
        await document.exitFullscreen().catch(() => {})
      }
    } catch (error) {
      if (!shell || run !== generation) return
      mode = 'video'; action.disabled = false
      status.textContent = `${error.message} You can continue the prepared presentation.`
      shell.querySelector('.compiled-cancel').hidden = true
      send('unlock')
    } finally { if (frame && run === generation) frame.style.pointerEvents = '' }
  }
  function receive(event) {
    if (!frame || event.source !== frame.contentWindow || event.data?.type !== 'nadoc-compiled' || event.data.token !== token) return
    if (event.data.command === 'ready') action.disabled = false
    if (event.data.command === 'snapshot') void inspect(event.data.state)
    if (event.data.command === 'escape') close()
  }
  const keydown = event => {
    if (shell && mode !== 'inspection' && event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); close() }
  }
  window.addEventListener('keydown', keydown, true)
  window.addEventListener('message', receive)
  function open(url, compiled) {
    close(); beforeStart?.()
    current = compiled; token = Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')
    shell = document.createElement('section'); shell.className = 'compiled-app-player'
    shell.innerHTML = `<div class="compiled-app-toolbar"><button class="btn compiled-inspect">Inspect in 3D</button><button class="btn compiled-cancel" hidden>Cancel loading</button><button class="btn compiled-fullscreen">Fullscreen</button><button class="btn compiled-close">Close presentation</button><span role="status"></span></div>`
    action = shell.querySelector('.compiled-inspect'); action.disabled = true; status = shell.querySelector('[role="status"]')
    frame = document.createElement('iframe'); frame.title = 'Compiled presentation'
    frame.setAttribute('sandbox', 'allow-scripts')
    frame.addEventListener('load', () => send('connect'))
    frame.src = url; shell.append(frame); viewport.append(shell)
    action.onclick = () => mode === 'inspection' ? resume() : send('snapshot')
    shell.querySelector('.compiled-cancel').onclick = () => {
      generation++; inspection.release(); mode = 'video'; action.disabled = false
      frame.style.pointerEvents = ''; status.textContent = 'Loading cancelled. Prepared playback remains available.'
      shell.querySelector('.compiled-cancel').hidden = true; send('unlock')
    }
    shell.querySelector('.compiled-close').onclick = close
    shell.querySelector('.compiled-fullscreen').onclick = () => viewport.requestFullscreen?.().catch(() => { status.textContent = 'Fullscreen unavailable' })
  }
  return { open, close,
    onPlayerEvent(event) {
      if (mode === 'preparing' && status && event.type === 'baking_progress') {
        status.textContent = event.label || `Preparing live 3D${event.total > 0 ? ` · ${event.done ?? 0}/${event.total}` : '…'}`
      }
      return inspection.onPlayerEvent(event)
    },
    dispose() { close(); window.removeEventListener('message', receive); window.removeEventListener('keydown', keydown, true) },
  }
}
