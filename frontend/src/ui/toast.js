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
