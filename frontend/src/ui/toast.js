/**
 * Toast notifications.
 *
 * Backward-compatible API:
 *   showToast(msg)                       — info, default 2200 ms
 *   showToast(msg, 4000)                 — info, custom duration
 *   showToast(msg, { severity, ... })    — full options form
 *   showPersistentToast(msg, options?)   — stays until dismissed
 *   dismissToast()                       — clear all
 *
 * Options:
 *   severity:  'info' | 'success' | 'warning' | 'error'   (default 'info')
 *   loading:   true — prepend an animated activity spinner
 *   duration:  ms (default 2200; ignored by showPersistentToast)
 *   action:    { label, onClick }  — adds a button (e.g. "Undo")
 *
 * Toasts stack vertically (newest below). Each is dismissible via × button.
 * Styling pulls from components.css (.toast / .toast--success/--warning/--error).
 */

const STACK_GAP_PX = 8
const _toasts = []  // { el, timer }

// CSS owns the base top/right position (see .toast in components.css).
// Stacking uses translateY so the base position stays under CSS control —
// otherwise inline `top` would override the canvas-area-aware CSS rule and
// the toast would re-stick to the viewport edge.
function _restack() {
  let offset = 0
  for (const t of _toasts) {
    t.el.style.transform = `translateY(${offset}px)`
    offset += t.el.offsetHeight + STACK_GAP_PX
  }
}

function _removeToast(t) {
  const idx = _toasts.indexOf(t)
  if (idx < 0) return
  _toasts.splice(idx, 1)
  if (t.timer) clearTimeout(t.timer)
  t.el.classList.remove('toast--visible')
  // wait for fade-out before removing
  setTimeout(() => {
    if (t.el.parentNode) t.el.parentNode.removeChild(t.el)
    _restack()
  }, 200)
  _restack()
}

function _createToast(msg, severity) {
  const el = document.createElement('div')
  el.className = 'toast'
  if (severity && severity !== 'info') el.classList.add(`toast--${severity}`)
  // layout: message [action] [×]
  el.style.display = 'flex'
  el.style.alignItems = 'center'
  el.style.gap = '8px'

  const msgEl = document.createElement('span')
  msgEl.className = 'toast-message'
  msgEl.textContent = msg
  msgEl.style.flex = '1'
  el.appendChild(msgEl)

  document.body.appendChild(el)
  // force layout so transition runs
  void el.offsetHeight
  el.classList.add('toast--visible')
  return el
}

function _addActionButton(toastEl, action, onClickWrapper) {
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.textContent = action.label
  btn.className = 'btn btn--ghost btn--sm'
  btn.style.flex = '0 0 auto'
  btn.style.fontSize = 'var(--text-sm)'
  btn.addEventListener('click', (e) => {
    e.stopPropagation()
    try { action.onClick?.() } finally { onClickWrapper() }
  })
  toastEl.appendChild(btn)
}

function _addCloseButton(toastEl, onClose) {
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.setAttribute('aria-label', 'Dismiss')
  btn.textContent = '×'
  btn.style.cssText = [
    'background:none', 'border:none', 'color:var(--color-text-muted)',
    'font-size:18px', 'line-height:1', 'cursor:pointer', 'padding:0 2px',
    'flex:0 0 auto',
  ].join(';')
  btn.addEventListener('click', (e) => { e.stopPropagation(); onClose() })
  toastEl.appendChild(btn)
}

function _normalizeOpts(arg2) {
  if (typeof arg2 === 'number') return { duration: arg2 }
  if (arg2 && typeof arg2 === 'object') return arg2
  return {}
}

/**
 * Show a brief toast.
 * @param {string} msg
 * @param {number | { duration?: number, severity?: string, action?: {label, onClick} }} [optsOrDuration]
 */
export function showToast(msg, optsOrDuration) {
  const opts = _normalizeOpts(optsOrDuration)
  const duration = opts.duration ?? 2200
  const severity = opts.severity ?? 'info'

  const el = _createToast(msg, severity)
  const t = { el, timer: null }
  _toasts.push(t)

  if (opts.action) _addActionButton(el, opts.action, () => _removeToast(t))
  _addCloseButton(el, () => _removeToast(t))

  _restack()
  t.timer = setTimeout(() => _removeToast(t), duration)
}

/**
 * Show a persistent toast that stays until dismissToast() is called.
 * Persistent toasts are de-duplicated by message — calling twice with the same
 * message just keeps the existing toast (matches legacy "single slot" behavior
 * used during progress polling).
 * @param {string} msg
 * @param {{ severity?: string, action?: {label, onClick} }} [opts]
 */
export function showPersistentToast(msg, opts = {}) {
  // Find existing persistent toast (timer === null marks persistent)
  const existing = _toasts.find((t) => t.timer === null && t.el.dataset.persistent === '1')
  if (existing) {
    const span = existing.el.querySelector('.toast-message')
    if (span) span.textContent = msg
    existing.el.classList.remove('toast--success', 'toast--warning', 'toast--error')
    const severity = opts.severity ?? 'info'
    if (severity !== 'info') existing.el.classList.add(`toast--${severity}`)
    if (opts.loading && !existing.el.querySelector('.nadoc-spinner')) {
      const spinner = document.createElement('span')
      spinner.className = 'nadoc-spinner'
      spinner.setAttribute('aria-hidden', 'true')
      spinner.style.flex = '0 0 auto'
      existing.el.insertBefore(spinner, existing.el.firstChild)
      existing.el.setAttribute('role', 'status')
      existing.el.setAttribute('aria-live', 'polite')
    }
    if (!opts.loading) {
      existing.el.querySelector('.nadoc-spinner')?.remove()
      existing.el.removeAttribute('role')
      existing.el.removeAttribute('aria-live')
    }
    // A persistent toast is a single reusable slot. Repurposing that slot must
    // also replace its controls; otherwise a roll-complete message can retain a
    // prior Cancel action and omit the required "Return to latest" affordance.
    for (const button of existing.el.querySelectorAll('button')) button.remove()
    if (opts.action) _addActionButton(existing.el, opts.action, () => _removeToast(existing))
    _addCloseButton(existing.el, () => _removeToast(existing))
    _restack()
    return
  }
  const severity = opts.severity ?? 'info'
  const el = _createToast(msg, severity)
  el.dataset.persistent = '1'
  if (opts.loading) {
    const spinner = document.createElement('span')
    spinner.className = 'nadoc-spinner'
    spinner.setAttribute('aria-hidden', 'true')
    spinner.style.flex = '0 0 auto'
    el.insertBefore(spinner, el.firstChild)
    el.setAttribute('role', 'status')
    el.setAttribute('aria-live', 'polite')
  }
  const t = { el, timer: null }
  _toasts.push(t)
  if (opts.action) _addActionButton(el, opts.action, () => _removeToast(t))
  _addCloseButton(el, () => _removeToast(t))
  _restack()
}

/**
 * Dismiss persistent toasts. Transient toasts (those with timers) are left to
 * fade on their own — matches legacy single-slot behavior where dismissToast()
 * was paired with showPersistentToast() to clear a "Loading…" message.
 */
export function dismissToast() {
  const snapshot = _toasts.filter((t) => t.timer === null)
  for (const t of snapshot) _removeToast(t)
}

// ── Cursor toast (small label that appears next to the mouse pointer) ────────
let _cursorToastEl = null
let _cursorToastTimer = null

function _getOrCreateCursorToast() {
  if (!_cursorToastEl) {
    _cursorToastEl = document.createElement('div')
    _cursorToastEl.style.cssText = [
      'position:fixed', 'pointer-events:none', 'z-index:var(--z-tooltip)',
      'background:var(--color-bg-raised)', 'color:var(--color-text-primary)',
      'font-size:var(--text-xs)', 'font-family:var(--font-ui)',
      'padding:3px 8px', 'border-radius:var(--radius-sm)',
      'border:1px solid var(--color-border-default)', 'white-space:nowrap',
      'opacity:0', 'transition:opacity 0.15s',
    ].join(';')
    document.body.appendChild(_cursorToastEl)
  }
  return _cursorToastEl
}

/**
 * Show a brief label next to the cursor position.
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
