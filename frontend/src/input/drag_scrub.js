/**
 * Drag-scrub for <input type="number">.
 *
 * Standard CAD/DAW convention: click on the input and drag vertically (or
 * horizontally) to change its value. Default step is read from the input's
 * `step` attribute (fallback 1). Modifiers:
 *
 *   Shift   — fine scrub  (step × 0.1)
 *   Ctrl    — coarse scrub (step × 10)
 *
 * The drag suppresses the click-to-focus that would otherwise pop the system
 * spinner; double-click still focuses for normal typing. The element gets a
 * `cursor: ns-resize` hint on hover.
 *
 * Usage:
 *   import { attachDragScrub } from '../input/drag_scrub.js'
 *   attachDragScrub(myInputEl)
 *
 *   // Or scan a panel root for all eligible inputs:
 *   attachAllDragScrub(panelEl)
 *
 * Re-attaching the same element is idempotent.
 */

const _ATTACHED = new WeakSet()
const DRAG_THRESHOLD_PX = 3   // ignore tiny mouse jitter
const PX_PER_STEP = 4         // 1 step per N pixels of drag

/**
 * Attach drag-scrub to a single number input.
 * @param {HTMLInputElement} input
 * @param {{ axis?: 'y'|'x' }} [opts]
 */
export function attachDragScrub(input, opts = {}) {
  if (!input || input.tagName !== 'INPUT' || input.type !== 'number') return
  if (_ATTACHED.has(input)) return
  _ATTACHED.add(input)

  const axis = opts.axis ?? 'y'
  input.style.cursor = 'ns-resize'

  let _down = null    // { x, y, value0, startedDrag }
  let _dragged = false

  input.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return
    if (document.activeElement === input) return   // typing mode → don't scrub
    const step = parseFloat(input.step) || 1
    const value0 = parseFloat(input.value) || 0
    _down = { x: e.clientX, y: e.clientY, value0, step }
    _dragged = false
  })

  function _onMove(e) {
    if (!_down) return
    const dx = e.clientX - _down.x
    const dy = e.clientY - _down.y
    if (!_dragged) {
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return
      _dragged = true
      input.setPointerCapture?.(e.pointerId)
    }
    const delta = axis === 'y' ? -dy : dx
    const mod = e.shiftKey ? 0.1 : (e.ctrlKey || e.metaKey ? 10 : 1)
    const stepEff = _down.step * mod
    const newVal = _down.value0 + (delta / PX_PER_STEP) * stepEff
    // Honor min/max if defined
    const min = input.min !== '' ? parseFloat(input.min) : -Infinity
    const max = input.max !== '' ? parseFloat(input.max) :  Infinity
    const clamped = Math.max(min, Math.min(max, newVal))
    // Format to step precision so the input doesn't show 14.0000001 etc.
    const precision = stepEff < 1 ? Math.max(0, -Math.floor(Math.log10(stepEff))) : 0
    input.value = clamped.toFixed(precision)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  }

  function _onUp() {
    if (_dragged) {
      input.dispatchEvent(new Event('change', { bubbles: true }))
    }
    _down = null
    _dragged = false
  }

  // Use window-level listeners so dragging outside the input still tracks.
  input.addEventListener('pointermove', _onMove)
  window.addEventListener('pointermove', _onMove)
  window.addEventListener('pointerup', _onUp)

  // Suppress the focus-on-click if a real drag happened; otherwise let the
  // browser focus the input so typing/scroll-spinner still work.
  input.addEventListener('click', (e) => {
    if (_dragged) { e.preventDefault(); _dragged = false }
  })
}

/**
 * Scan a container for all <input type="number"> and attach drag-scrub.
 * Skips inputs with `data-no-scrub` opt-out.
 */
export function attachAllDragScrub(root) {
  if (!root) return
  for (const inp of root.querySelectorAll('input[type="number"]:not([data-no-scrub])')) {
    attachDragScrub(inp)
  }
}
