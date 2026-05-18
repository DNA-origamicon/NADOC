/**
 * Sidebar resize — drag-to-resize on the inside edge of the left/right panels,
 * with per-panel width persisted to localStorage.
 *
 * Handle DOM lives in index.html as `.panel-resize-handle[data-resize="left|right"]`
 * inside each sidebar. CSS positions the handle on the inner edge with
 * `cursor: ew-resize`.
 *
 * Width clamps: MIN..MAX (px). Below MIN the panel hides itself via the
 * existing `.hidden` class so it can still be re-opened from the tab strip.
 * Above MAX is a hard cap to keep the canvas usable.
 *
 * Usage:
 *   initSidebarResize()
 *
 * No-ops if the panels / handles aren't in the DOM yet (e.g. tests).
 */

const MIN_PX = 200
const MAX_PX = 600
const LS_LEFT  = 'nadoc.leftPanel.width'
const LS_RIGHT = 'nadoc.rightPanel.width'

function _readWidth(key) {
  const raw = localStorage.getItem(key)
  if (!raw) return null
  const n = parseInt(raw, 10)
  if (!Number.isFinite(n)) return null
  return Math.max(MIN_PX, Math.min(MAX_PX, n))
}

function _writeWidth(key, w) {
  localStorage.setItem(key, String(Math.round(w)))
}

function _applyWidth(panel, w) {
  panel.style.width = `${Math.round(w)}px`
}

function _wireHandle(side) {
  const panel = document.getElementById(side === 'left' ? 'left-panel' : 'right-panel')
  if (!panel) return
  const handle = panel.querySelector(`.panel-resize-handle[data-resize="${side}"]`)
  if (!handle) return
  const lsKey = side === 'left' ? LS_LEFT : LS_RIGHT

  // Restore persisted width on init (only if the panel isn't currently hidden).
  const saved = _readWidth(lsKey)
  if (saved != null && !panel.classList.contains('hidden')) {
    _applyWidth(panel, saved)
  }

  let _dragging = false
  let _startX   = 0
  let _startW   = 0

  handle.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return
    _dragging = true
    _startX = e.clientX
    _startW = panel.getBoundingClientRect().width
    handle.classList.add('is-dragging')
    handle.setPointerCapture?.(e.pointerId)
    // Disable the panel's CSS width transition during drag — otherwise the
    // panel chases the pointer with a lag. Restored on pointerup.
    panel.dataset._prevTransition = panel.style.transition
    panel.style.transition = 'none'
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'ew-resize'
  })

  window.addEventListener('pointermove', (e) => {
    if (!_dragging) return
    const dx = e.clientX - _startX
    // For the right panel the handle is on its LEFT edge, so dragging right
    // shrinks the panel; flip the sign.
    const delta = side === 'left' ? dx : -dx
    let w = _startW + delta
    if (w < MIN_PX * 0.5) w = 0   // dragged way past min → snap shut
    else                  w = Math.max(MIN_PX, Math.min(MAX_PX, w))
    _applyWidth(panel, w)
  })

  window.addEventListener('pointerup', () => {
    if (!_dragging) return
    _dragging = false
    handle.classList.remove('is-dragging')
    panel.style.transition = panel.dataset._prevTransition ?? ''
    delete panel.dataset._prevTransition
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
    const w = panel.getBoundingClientRect().width
    if (w < MIN_PX * 0.5) {
      // Snap-shut: hide via .hidden class (cooperates with tab-strip toggle).
      panel.classList.add('hidden')
      panel.style.width = ''   // let .hidden take over
    } else {
      _writeWidth(lsKey, w)
    }
  })
}

export function initSidebarResize() {
  _wireHandle('left')
  _wireHandle('right')
}
