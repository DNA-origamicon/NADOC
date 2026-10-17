// Shared right-click arbitration for canvas menus. Track the entire gesture,
// not just the distance between its endpoints: orbiting out and back is still
// a drag. Never let a deferred menu consume OrbitControls' pointerup event.
const trackers = new WeakMap()
const DRAG_THRESHOLD = 4

function trackRightClicks(canvas) {
  if (trackers.has(canvas)) return
  trackers.set(canvas, true)
  const view = canvas.ownerDocument?.defaultView ?? window
  let gesture = null
  let cleanup = () => {}

  function start(event) {
    if (event.button !== 2) return
    cleanup()
    const current = gesture = {
      x: event.clientX, y: event.clientY, pointerId: event.pointerId,
      held: true, dragged: false, requested: false, delivered: false,
    }
    const matches = e => current.pointerId == null || e.pointerId == null || e.pointerId === current.pointerId
    const move = e => {
      if (!matches(e)) return
      if (Math.hypot(e.clientX - current.x, e.clientY - current.y) > DRAG_THRESHOLD) current.dragged = true
    }
    const cancel = () => {
      current.dragged = true
      current.held = false
      cleanup()
    }
    const up = e => {
      if (e.button !== 2 || !matches(e)) return
      move(e)
      current.held = false
      cleanup()
      // On Linux contextmenu arrives at press time. Replay it after all
      // pointerup listeners (including OrbitControls) have finished. A normal
      // release-time contextmenu may win first; do not deliver it twice.
      if (current.requested && !current.dragged) queueMicrotask(() => {
        if (gesture !== current || current.dragged || current.delivered) return
        canvas.dispatchEvent(new view.MouseEvent('contextmenu', {
          bubbles: true, cancelable: true, button: 2, buttons: 0,
          clientX: e.clientX, clientY: e.clientY,
          ctrlKey: e.ctrlKey, shiftKey: e.shiftKey, altKey: e.altKey, metaKey: e.metaKey,
        }))
      })
    }
    const pointerCancel = e => { if (matches(e)) cancel() }
    cleanup = () => {
      view.removeEventListener('pointermove', move, true)
      view.removeEventListener('pointerup', up, true)
      view.removeEventListener('pointercancel', pointerCancel, true)
      view.removeEventListener('blur', cancel)
    }
    view.addEventListener('pointermove', move, true)
    view.addEventListener('pointerup', up, true)
    view.addEventListener('pointercancel', pointerCancel, true)
    view.addEventListener('blur', cancel)
  }

  canvas.addEventListener('pointerdown', start, true)
  canvas.addEventListener('contextmenu', e => {
    e.preventDefault()
    // Keyboard context-menu commands do not belong to a prior mouse drag.
    if (e.button !== 2) return
    if (!gesture && (e.buttons & 2)) start(e)
    if (!gesture) return
    if (Math.hypot(e.clientX - gesture.x, e.clientY - gesture.y) > DRAG_THRESHOLD) gesture.dragged = true
    if (gesture.held || (e.buttons & 2)) {
      gesture.requested = true
      e.stopImmediatePropagation()
    } else if (gesture.dragged || gesture.delivered) {
      e.stopImmediatePropagation()
    } else {
      gesture.delivered = true
    }
  }, true)
}

/** Wrap every canvas menu before registering it, in either event phase.
 * The shared capture gate suppresses drag menus and replays press-time menus
 * after release. Bodies always receive a contextmenu event, never pointerup.
 */
export function deferrableContextMenu(canvas, body, _options = {}) {
  trackRightClicks(canvas)
  return e => { e.preventDefault(); body(e) }
}
