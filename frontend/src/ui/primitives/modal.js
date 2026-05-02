/**
 * Modal factory — single source of truth for overlay+box+header+actions.
 *
 * Replaces the bespoke modal DOM construction scattered across:
 *   - file_browser.js
 *   - any other JS that allocates its own overlay+modal
 *
 * Usage:
 *   const m = createModal({
 *     title: 'Open File',
 *     size: 'md',
 *     body: someElement,
 *     actions: [
 *       createButton({ label: 'Cancel', onClick: () => m.close() }),
 *       createButton({ label: 'Open', variant: 'primary', onClick: ... }),
 *     ],
 *     onClose: () => { ... },
 *   })
 *   m.open()
 *   ...
 *   m.close()
 */

import { el, detach } from './dom.js'

/**
 * @param {object} opts
 * @param {string|HTMLElement} [opts.title]
 * @param {HTMLElement|HTMLElement[]} [opts.body]
 * @param {HTMLElement[]} [opts.actions]            — buttons in the footer
 * @param {'sm'|'md'|'lg'|'xl'} [opts.size='md']
 * @param {boolean} [opts.closable=true]            — show × close button
 * @param {boolean} [opts.dismissOnBackdrop=true]   — click overlay to close
 * @param {boolean} [opts.dismissOnEscape=true]
 * @param {() => boolean|void} [opts.onClose]       — return false to prevent close
 * @param {string} [opts.className]                 — extra class on the modal box
 * @returns {{
 *   root: HTMLElement,
 *   overlay: HTMLElement,
 *   body: HTMLElement,
 *   header: HTMLElement,
 *   actions: HTMLElement,
 *   open: () => void,
 *   close: () => void,
 *   isOpen: () => boolean,
 * }}
 */
export function createModal(opts = {}) {
  const {
    title,
    body,
    actions = [],
    size = 'md',
    closable = true,
    dismissOnBackdrop = true,
    dismissOnEscape = true,
    onClose,
    className,
  } = opts

  let _isOpen = false
  let _escListener = null

  // ── Header ────────────────────────────────────────────────────────────
  const titleEl = el('div', {
    className: 'modal__title',
    children: typeof title === 'string'
      ? [title]
      : (title ? [title] : undefined),
  })

  const closeBtn = closable
    ? el('button', {
        className: 'modal__close',
        attrs: { type: 'button', 'aria-label': 'Close' },
        text: '×',
        on: { click: () => close() },
      })
    : null

  const headerEl = el('div', {
    className: 'modal__header',
    children: [titleEl, closeBtn],
  })

  // ── Body ─────────────────────────────────────────────────────────────
  const bodyChildren = Array.isArray(body) ? body : (body ? [body] : [])
  const bodyEl = el('div', {
    className: 'modal__body',
    children: bodyChildren,
  })

  // ── Actions ──────────────────────────────────────────────────────────
  const actionsEl = el('div', {
    className: 'modal__actions',
    children: actions,
  })
  if (actions.length === 0) actionsEl.style.display = 'none'

  // ── Modal box ────────────────────────────────────────────────────────
  const modalClasses = ['modal', `modal--${size}`]
  if (className) modalClasses.push(className)

  const modalEl = el('div', {
    className: modalClasses.join(' '),
    attrs: { role: 'dialog', 'aria-modal': 'true' },
    children: [headerEl, bodyEl, actionsEl],
  })

  // ── Overlay ──────────────────────────────────────────────────────────
  const overlayEl = el('div', {
    className: 'modal__overlay',
    children: [modalEl],
    on: dismissOnBackdrop ? {
      mousedown: (e) => { if (e.target === overlayEl) close() },
    } : undefined,
  })

  // ── Lifecycle ────────────────────────────────────────────────────────
  function open() {
    if (_isOpen) return
    document.body.appendChild(overlayEl)
    _isOpen = true
    if (dismissOnEscape) {
      _escListener = (e) => { if (e.key === 'Escape') close() }
      window.addEventListener('keydown', _escListener)
    }
  }

  function close() {
    if (!_isOpen) return
    if (typeof onClose === 'function') {
      const result = onClose()
      if (result === false) return  // veto
    }
    detach(overlayEl)
    _isOpen = false
    if (_escListener) {
      window.removeEventListener('keydown', _escListener)
      _escListener = null
    }
  }

  return {
    root: modalEl,
    overlay: overlayEl,
    header: headerEl,
    body: bodyEl,
    actions: actionsEl,
    open,
    close,
    isOpen: () => _isOpen,
  }
}
