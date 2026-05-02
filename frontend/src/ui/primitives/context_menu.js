/**
 * Context menu factory.
 *
 * Replaces the bespoke `position:fixed; z-index:9998; ...` context-menu
 * DOM scattered across:
 *   - main.js (right-click on strands / domains / nucleotides)
 *   - assembly_context_menu.js
 *
 * Items can be:
 *   { type: 'header', label }                — non-clickable section title
 *   { type: 'separator' }                    — horizontal divider
 *   { label, onClick, disabled?, icon?, shortcut? }
 *
 * Closes on:
 *   - selection (clicking an item)
 *   - click outside
 *   - Escape
 *   - scroll (optional)
 */

import { el, detach } from './dom.js'

/**
 * @param {object} opts
 * @param {number} opts.x — viewport-relative pixel coords for top-left
 * @param {number} opts.y
 * @param {Array} opts.items
 * @param {boolean} [opts.dismissOnScroll=true]
 * @param {() => void} [opts.onClose]
 * @returns {{ root: HTMLElement, close: () => void }}
 */
export function createContextMenu(opts = {}) {
  const { x, y, items = [], dismissOnScroll = true, onClose } = opts

  let _closed = false

  const menuEl = el('div', {
    className: 'context-menu',
    attrs: { role: 'menu' },
  })

  for (const item of items) {
    if (!item) continue
    if (item.type === 'separator') {
      menuEl.appendChild(el('div', { className: 'context-menu__separator' }))
      continue
    }
    if (item.type === 'header') {
      menuEl.appendChild(el('div', {
        className: 'context-menu__header',
        text: item.label,
      }))
      continue
    }

    const children = []
    if (item.icon)     children.push(item.icon)  // expects HTMLElement (SVG)
    children.push(el('span', { text: item.label }))
    if (item.shortcut) {
      children.push(el('span', {
        className: 'dropdown__shortcut',
        text: item.shortcut,
      }))
    }

    const itemEl = el('div', {
      className: 'context-menu__item' + (item.disabled ? ' context-menu__item--disabled' : ''),
      attrs: { role: 'menuitem' },
      children,
      on: !item.disabled ? {
        click: (e) => {
          e.stopPropagation()
          if (typeof item.onClick === 'function') item.onClick(e)
          close()
        },
      } : undefined,
    })
    menuEl.appendChild(itemEl)
  }

  // ── Position (after attach so we can measure) ──────────────────────
  function _position() {
    const rect = menuEl.getBoundingClientRect()
    let posX = x
    let posY = y
    if (posX + rect.width  > window.innerWidth)  posX = window.innerWidth  - rect.width  - 8
    if (posY + rect.height > window.innerHeight) posY = window.innerHeight - rect.height - 8
    if (posX < 0) posX = 8
    if (posY < 0) posY = 8
    menuEl.style.left = posX + 'px'
    menuEl.style.top  = posY + 'px'
  }

  // ── Outside-click / escape handlers ────────────────────────────────
  function _handleOutside(e) {
    if (!menuEl.contains(e.target)) close()
  }
  function _handleEscape(e) {
    if (e.key === 'Escape') close()
  }
  function _handleScroll() {
    if (dismissOnScroll) close()
  }

  function close() {
    if (_closed) return
    _closed = true
    detach(menuEl)
    document.removeEventListener('mousedown', _handleOutside, true)
    document.removeEventListener('contextmenu', _handleOutside, true)
    window.removeEventListener('keydown', _handleEscape)
    window.removeEventListener('scroll', _handleScroll, true)
    if (typeof onClose === 'function') onClose()
  }

  // ── Open ───────────────────────────────────────────────────────────
  document.body.appendChild(menuEl)
  _position()
  // Defer outside-click binding so the originating click doesn't immediately dismiss
  setTimeout(() => {
    if (_closed) return
    document.addEventListener('mousedown', _handleOutside, true)
    document.addEventListener('contextmenu', _handleOutside, true)
    window.addEventListener('keydown', _handleEscape)
    window.addEventListener('scroll', _handleScroll, true)
  }, 0)

  return { root: menuEl, close }
}
