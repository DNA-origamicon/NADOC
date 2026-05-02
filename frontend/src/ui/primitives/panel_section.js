/**
 * Collapsible panel section factory.
 *
 * Builds the standard panel section with header (uppercase title +
 * chevron) and body. Used across left/right side panels.
 *
 *   const s = createPanelSection({ title: 'Camera Poses', collapsible: true })
 *   s.body.appendChild(somethingForBody)
 *   parent.appendChild(s.root)
 */

import { el } from './dom.js'

/**
 * @param {object} opts
 * @param {string} opts.title
 * @param {boolean} [opts.collapsible=false]
 * @param {boolean} [opts.defaultOpen=true]
 * @param {string} [opts.id]
 * @param {(open: boolean) => void} [opts.onToggle]
 * @returns {{
 *   root: HTMLElement, header: HTMLElement, body: HTMLElement,
 *   open: () => void, close: () => void, toggle: () => void,
 *   isOpen: () => boolean,
 * }}
 */
export function createPanelSection(opts = {}) {
  const {
    title,
    collapsible = false,
    defaultOpen = true,
    id,
    onToggle,
  } = opts

  let _open = defaultOpen

  const titleEl = el('span', {
    className: 'panel-section__title',
    text: title,
  })

  // Chevron — replaced with Lucide icon in Phase 5
  const chevronEl = el('span', {
    className: 'panel-section__chevron',
    text: '▾',
  })

  const headerEl = el('div', {
    className: 'panel-section__header' + (collapsible ? ' panel-section__header--clickable' : ''),
    children: [titleEl, collapsible ? chevronEl : null],
  })

  const bodyEl = el('div', { className: 'panel-section__body' })

  const rootEl = el('div', {
    className: 'panel-section' + (_open ? '' : ' panel-section--collapsed'),
    id,
    children: [headerEl, bodyEl],
  })

  function _apply() {
    rootEl.classList.toggle('panel-section--collapsed', !_open)
  }

  function open()   { if (!_open) { _open = true;  _apply(); onToggle && onToggle(true) } }
  function close()  { if (_open)  { _open = false; _apply(); onToggle && onToggle(false) } }
  function toggle() { _open ? close() : open() }

  if (collapsible) {
    headerEl.addEventListener('click', toggle)
  }

  return {
    root: rootEl,
    header: headerEl,
    body: bodyEl,
    open,
    close,
    toggle,
    isOpen: () => _open,
  }
}
