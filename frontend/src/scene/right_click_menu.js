// right_click_menu.js — cross-platform right-click-vs-pan discrimination.
//
// The app maps right-drag to camera pan (OrbitControls) and right-CLICK to its own
// context menus. To tell a click from a pan it measures how far the pointer moved
// between right-button-down and the browser's `contextmenu` event. That only works
// if `contextmenu` fires on button RELEASE (after the drag has moved the pointer):
//
//   • Windows / macOS browsers fire `contextmenu` on RELEASE  → move check sees the
//     drag, correctly suppresses the menu. ✓
//   • Linux (GTK: Firefox and Chromium) fire `contextmenu` on PRESS, before any
//     movement → the move check always reads ~0, so every right-drag-pan is mistaken
//     for a click and pops the menu, blocking the pan. ✗
//
// Fix: when the right button is still held at `contextmenu` time (the Linux press
// case), defer the handler body to the coming `pointerup` — by then the pan has
// moved the pointer and the body's own move check works. When the button is already
// released (Windows/mac), run the body immediately, exactly as before.
//
// The native menu is always suppressed here (the app renders its own); this is
// belt-and-suspenders with OrbitControls' own contextmenu suppression.

/**
 * Wrap a `contextmenu` handler body so it fires at a point where a right-drag-pan
 * has already moved the pointer, on every platform.
 *
 * @param {EventTarget} canvas   the element the contextmenu listener is attached to
 * @param {(e: Event) => void} body  the original handler logic (does its own move
 *   check / raycasting / menu show). On the deferred path it receives the `pointerup`
 *   event, whose clientX/clientY is the release position — same shape the move check
 *   expects.
 * @param {{capture?: boolean}} [opts]  register the deferred pointerup/pointercancel
 *   listeners in the same phase as the wrapped contextmenu listener.
 * @returns {(e: Event) => void} the listener to pass to addEventListener('contextmenu', …)
 */
export function deferrableContextMenu(canvas, body, { capture = false } = {}) {
  return function onContextMenu(e) {
    e.preventDefault() // app renders its own menus — never the native one
    // Bit 1 (value 2) of MouseEvent.buttons = right button. Still held ⇒ this is a
    // press-time contextmenu (Linux) and a pointerup is still coming.
    if (e.buttons & 2) {
      const cleanup = () => {
        canvas.removeEventListener('pointerup', onUp, capture)
        canvas.removeEventListener('pointercancel', onCancel, capture)
      }
      const onUp = up => { cleanup(); body(up) }
      const onCancel = () => { cleanup() }
      canvas.addEventListener('pointerup', onUp, capture)
      canvas.addEventListener('pointercancel', onCancel, capture)
      return
    }
    // Button already released (Windows/mac) — decide now; behavior unchanged.
    body(e)
  }
}
