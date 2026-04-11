let _toastTimeout = null

function _getOrCreateToast() {
  let toast = document.getElementById('_toast_msg')
  if (!toast) {
    toast = document.createElement('div')
    toast.id = '_toast_msg'
    toast.style.cssText = [
      'position:fixed', 'top:44px', 'right:308px',
      'background:rgba(30,40,50,0.92)', 'color:#cde', 'font-size:12px',
      'padding:6px 12px', 'border-radius:4px', 'pointer-events:none',
      'transition:opacity 0.4s', 'z-index:9999',
    ].join(';')
    document.body.appendChild(toast)
  }
  return toast
}

/**
 * Show a brief toast notification in the top-right of the viewport.
 * @param {string} msg
 * @param {number} durationMs
 */
export function showToast(msg, durationMs = 2200) {
  const toast = _getOrCreateToast()
  toast.textContent = msg
  toast.style.opacity = '1'
  clearTimeout(_toastTimeout)
  _toastTimeout = setTimeout(() => { toast.style.opacity = '0' }, durationMs)
}

/**
 * Show a persistent toast that stays visible until dismissToast() is called.
 * @param {string} msg
 */
export function showPersistentToast(msg) {
  const toast = _getOrCreateToast()
  toast.textContent = msg
  toast.style.opacity = '1'
  clearTimeout(_toastTimeout)
  _toastTimeout = null
}

/**
 * Dismiss the current toast immediately.
 */
export function dismissToast() {
  clearTimeout(_toastTimeout)
  _toastTimeout = null
  const toast = document.getElementById('_toast_msg')
  if (toast) toast.style.opacity = '0'
}

// ── Cursor toast (small label that appears next to the mouse pointer) ────────
let _cursorToastEl = null
let _cursorToastTimer = null

function _getOrCreateCursorToast() {
  if (!_cursorToastEl) {
    _cursorToastEl = document.createElement('div')
    _cursorToastEl.style.cssText = [
      'position:fixed', 'pointer-events:none', 'z-index:10000',
      'background:rgba(22,27,34,0.92)', 'color:#e6edf3', 'font-size:11px',
      'font-family:monospace', 'padding:3px 8px', 'border-radius:4px',
      'border:1px solid #30363d', 'white-space:nowrap',
      'opacity:0', 'transition:opacity 0.15s',
    ].join(';')
    document.body.appendChild(_cursorToastEl)
  }
  return _cursorToastEl
}

/**
 * Show a brief label next to the cursor position.
 * @param {string} msg
 * @param {number} x  — clientX
 * @param {number} y  — clientY
 * @param {number} durationMs
 */
export function showCursorToast(msg, x, y, durationMs = 600) {
  const el = _getOrCreateCursorToast()
  el.textContent = msg
  el.style.left = `${x + 14}px`
  el.style.top  = `${y - 10}px`
  el.style.opacity = '1'
  clearTimeout(_cursorToastTimer)
  _cursorToastTimer = setTimeout(() => { el.style.opacity = '0' }, durationMs)
}
