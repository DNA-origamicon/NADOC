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
 *   { type: 'custom', el }                   — caller-owned HTMLElement passthrough
 *                                              (e.g. a hover-flyout submenu the
 *                                              primitive can't express); the menu
 *                                              does NOT auto-dismiss on clicks
 *                                              inside it — wire that in the el.
 *   { label, onClick, disabled?, danger?, icon?, shortcut? }
 *
 * Closes on:
 *   - selection (clicking an item)
 *   - click outside
 *   - Escape
 *   - scroll (optional)
 */

import { el, detach } from './dom.js'

/**
 * Pure: fit a menu of `width`×`height` inside the viewport, anchored at (x, y).
 *
 * Rules (ported from the 3D viewport's `_placeMenu`, which had them and this
 * primitive did not — the tall strand menu was clipped without them):
 *   • Overflows the right edge → shift left so it ends `margin` from the edge.
 *   • Overflows the bottom → **grow upward**: anchor the bottom near the cursor
 *     instead of clipping. A menu right-clicked low on screen stays fully visible.
 *   • Taller than the whole viewport even when flipped → cap it at the viewport
 *     height and let it scroll (`maxHeight` non-null), pinned to the top margin.
 *   • Never lands closer than `margin` to the top or left edge.
 *
 * @returns {{left: number, top: number, maxHeight: number|null}}
 */
export function placeMenu({
  x, y, width, height, viewportW, viewportH, margin = 8,
}) {
  const maxH = viewportH - margin * 2

  let left = x
  if (left + width > viewportW) left = viewportW - width - margin
  if (left < margin) left = margin

  let top = y
  let maxHeight = null
  if (height > maxH) {
    maxHeight = maxH
    top = margin
  } else if (top + height > viewportH) {
    top = viewportH - height - margin
  }
  if (top < margin) top = margin

  return { left, top, maxHeight }
}

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
    if (item.type === 'custom') {
      if (item.el) menuEl.appendChild(item.el)
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
      className: 'context-menu__item'
        + (item.disabled ? ' context-menu__item--disabled' : '')
        + (item.danger ? ' context-menu__item--danger' : ''),
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
    const { left, top, maxHeight } = placeMenu({
      x, y, width: rect.width, height: rect.height,
      viewportW: window.innerWidth, viewportH: window.innerHeight,
    })
    if (maxHeight != null) {
      menuEl.style.maxHeight = `${maxHeight}px`
      menuEl.style.overflowY = 'auto'
    }
    menuEl.style.left = left + 'px'
    menuEl.style.top  = top + 'px'
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
