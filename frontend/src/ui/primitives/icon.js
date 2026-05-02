/**
 * Icon registry — Lucide-derived SVG paths.
 *
 * Usage in JS:
 *   import { icon, inflateIcons } from './primitives/icon.js'
 *   button.appendChild(icon('chevron-down', { size: 14 }))
 *
 * Usage in HTML:
 *   <span class="icon" data-icon="chevron-down"></span>
 *   ...then call inflateIcons() once on DOMContentLoaded.
 *
 * Conventions (all from Lucide):
 *   - 24×24 viewBox, stroke-width=2, stroke-linecap=round, stroke-linejoin=round
 *   - color via currentColor (no explicit color in registry)
 *   - inner markup only — no <svg> wrapper
 */

import { el } from './dom.js'

const SVG_NS = 'http://www.w3.org/2000/svg'

const _ICONS = {
  // ── Chevrons / arrows ───────────────────────────────────────────────
  'chevron-down':  '<path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'chevron-up':    '<path d="m18 15-6-6-6 6" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'chevron-right': '<path d="m9 18 6-6-6-6" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'chevron-left':  '<path d="m15 18-6-6 6-6" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'arrow-up':      '<path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'arrow-down':    '<path d="M12 5v14M19 12l-7 7-7-7" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'arrow-left':    '<path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'arrow-right':   '<path d="M5 12h14M12 5l7 7-7 7" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',

  // ── CRUD ────────────────────────────────────────────────────────────
  'plus':   '<path d="M5 12h14M12 5v14" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'minus':  '<path d="M5 12h14" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'x':      '<path d="M18 6 6 18M6 6l12 12" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'check':  '<path d="M20 6 9 17l-5-5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'pencil': '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="m15 5 4 4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'trash':  '<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M10 11v6M14 11v6" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'copy':   '<rect width="14" height="14" x="8" y="8" rx="2" ry="2" stroke="currentColor" stroke-width="2" fill="none"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'save':   '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><polyline points="17 21 17 13 7 13 7 21" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><polyline points="7 3 7 8 15 8" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',

  // ── Media playback ──────────────────────────────────────────────────
  'play':         '<polygon points="6 3 20 12 6 21 6 3" stroke="currentColor" stroke-width="2" fill="currentColor" stroke-linejoin="round"/>',
  'pause':        '<rect x="14" y="4" width="4" height="16" rx="1" stroke="currentColor" stroke-width="2" fill="currentColor"/><rect x="6" y="4" width="4" height="16" rx="1" stroke="currentColor" stroke-width="2" fill="currentColor"/>',
  'square':       '<rect width="16" height="16" x="4" y="4" rx="1" stroke="currentColor" stroke-width="2" fill="currentColor"/>',
  'skip-back':    '<polygon points="19 20 9 12 19 4 19 20" stroke="currentColor" stroke-width="2" fill="currentColor" stroke-linejoin="round"/><line x1="5" y1="19" x2="5" y2="5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  'skip-forward': '<polygon points="5 4 15 12 5 20 5 4" stroke="currentColor" stroke-width="2" fill="currentColor" stroke-linejoin="round"/><line x1="19" y1="5" x2="19" y2="19" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',

  // ── Visibility / state ──────────────────────────────────────────────
  'eye':       '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2" fill="none"/>',
  'eye-off':   '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><line x1="2" y1="2" x2="22" y2="22" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  'lock':      '<rect width="18" height="11" x="3" y="11" rx="2" ry="2" stroke="currentColor" stroke-width="2" fill="none"/><path d="M7 11V7a5 5 0 0 1 10 0v4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'unlock':    '<rect width="18" height="11" x="3" y="11" rx="2" ry="2" stroke="currentColor" stroke-width="2" fill="none"/><path d="M7 11V7a5 5 0 0 1 9.9-1" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',

  // ── Files ───────────────────────────────────────────────────────────
  'folder':     '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'file':       '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M14 2v4a2 2 0 0 0 2 2h4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'folder-up':  '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 10v6M9 13l3-3 3 3" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'download':   '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><polyline points="7 10 12 15 17 10" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><line x1="12" y1="15" x2="12" y2="3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  'upload':     '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><polyline points="17 8 12 3 7 8" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><line x1="12" y1="3" x2="12" y2="15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',

  // ── Misc UI ────────────────────────────────────────────────────────
  'settings':    '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2" fill="none"/>',
  'help-circle': '<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" fill="none"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><line x1="12" y1="17" x2="12.01" y2="17" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  'menu':        '<line x1="4" y1="6" x2="20" y2="6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="4" y1="12" x2="20" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="4" y1="18" x2="20" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  'more-vertical': '<circle cx="12" cy="12" r="1" stroke="currentColor" stroke-width="2" fill="currentColor"/><circle cx="12" cy="5" r="1" stroke="currentColor" stroke-width="2" fill="currentColor"/><circle cx="12" cy="19" r="1" stroke="currentColor" stroke-width="2" fill="currentColor"/>',
  'more-horizontal': '<circle cx="12" cy="12" r="1" stroke="currentColor" stroke-width="2" fill="currentColor"/><circle cx="19" cy="12" r="1" stroke="currentColor" stroke-width="2" fill="currentColor"/><circle cx="5" cy="12" r="1" stroke="currentColor" stroke-width="2" fill="currentColor"/>',
  'search':      '<circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2" fill="none"/><line x1="21" y1="21" x2="16.65" y2="16.65" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  'info':        '<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" fill="none"/><line x1="12" y1="16" x2="12" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="8" x2="12.01" y2="8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  'alert':       '<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" fill="none"/><line x1="12" y1="8" x2="12" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="16" x2="12.01" y2="16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  'refresh':     '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M21 3v5h-5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 21v-5h5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'external':    '<path d="M15 3h6v6M10 14 21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',

  // ── Domain (NADOC) ─────────────────────────────────────────────────
  'dna':         '<path d="M2 15c6.667-6 13.333 0 20-6" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 22a8 8 0 0 1-9-9c4-4 11-4 14 0M22 9a8 8 0 0 1-9-9c-4 4-4 11 0 14" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  'crosshair':   '<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" fill="none"/><line x1="22" y1="12" x2="18" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="6" y1="12" x2="2" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="6" x2="12" y2="2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="22" x2="12" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  'camera':      '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="13" r="3" stroke="currentColor" stroke-width="2" fill="none"/>',
  'layers':      '<path d="m12 2 9 5-9 5-9-5 9-5z" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="m3 17 9 5 9-5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="m3 12 9 5 9-5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
}

/** Map old unicode glyphs to canonical icon names (used by sweep/migrations). */
export const UNICODE_TO_ICON = {
  '▼': 'chevron-down',
  '▲': 'chevron-up',
  '▶': 'chevron-right',
  '◀': 'chevron-left',
  '×': 'x',
  '✓': 'check',
  '✗': 'x',
  '✎': 'pencil',
  '+': 'plus',
  '−': 'minus',
  '↑': 'arrow-up',
  '↓': 'arrow-down',
  '←': 'arrow-left',
  '→': 'arrow-right',
  '⏵': 'play',
  '⏸': 'pause',
  '⏹': 'square',
  '⌃': 'chevron-up',
  '⌄': 'chevron-down',
}

/**
 * @param {string} name
 * @param {object} [opts]
 * @param {number} [opts.size=16]
 * @param {string} [opts.color]
 * @param {string} [opts.className]
 * @param {string} [opts.title]
 * @returns {SVGSVGElement|HTMLSpanElement}
 */
export function icon(name, opts = {}) {
  const { size = 16, color, className, title } = opts
  const path = _ICONS[name]
  if (!path) {
    return el('span', {
      className: 'icon icon--missing' + (className ? ' ' + className : ''),
      attrs: { 'data-icon': name, style: `display:inline-flex;width:${size}px;height:${size}px;align-items:center;justify-content:center` },
      text: '?',
    })
  }
  const svg = document.createElementNS(SVG_NS, 'svg')
  svg.setAttribute('viewBox', '0 0 24 24')
  svg.setAttribute('width', String(size))
  svg.setAttribute('height', String(size))
  svg.setAttribute('aria-hidden', title ? 'false' : 'true')
  if (title) {
    const titleEl = document.createElementNS(SVG_NS, 'title')
    titleEl.textContent = title
    svg.appendChild(titleEl)
  }
  if (color) svg.style.color = color
  svg.classList.add('icon')
  if (className) {
    for (const c of className.split(/\s+/)) if (c) svg.classList.add(c)
  }
  svg.insertAdjacentHTML('beforeend', path)
  return svg
}

/**
 * Walk the DOM and replace every `[data-icon]` element's content with the
 * corresponding SVG. Idempotent — sets `data-icon-inflated` after processing.
 *
 *   <span class="icon" data-icon="chevron-down"></span>
 *
 * Optionally pass a root (defaults to document.body).
 */
export function inflateIcons(root) {
  const scope = root || document.body
  if (!scope) return
  const nodes = scope.querySelectorAll('[data-icon]:not([data-icon-inflated])')
  for (const node of nodes) {
    const name = node.getAttribute('data-icon')
    const path = _ICONS[name]
    if (!path) {
      node.setAttribute('data-icon-inflated', 'missing')
      continue
    }
    // Preserve any sizing already on the element (via CSS or inline width/height)
    const sizeAttr = node.getAttribute('data-icon-size')
    const size = sizeAttr ? parseInt(sizeAttr, 10) : null
    node.innerHTML = ''
    const svg = document.createElementNS(SVG_NS, 'svg')
    svg.setAttribute('viewBox', '0 0 24 24')
    if (size) {
      svg.setAttribute('width', String(size))
      svg.setAttribute('height', String(size))
    } else {
      svg.setAttribute('width', '100%')
      svg.setAttribute('height', '100%')
    }
    svg.setAttribute('aria-hidden', 'true')
    svg.insertAdjacentHTML('beforeend', path)
    node.appendChild(svg)
    node.setAttribute('data-icon-inflated', 'true')
  }
}

/** Watch the DOM for newly-added [data-icon] elements and inflate them. */
export function observeIcons(root) {
  const scope = root || document.body
  if (!scope || typeof MutationObserver === 'undefined') return null
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType !== 1) continue
        if (node.matches && node.matches('[data-icon]')) inflateIcons(node.parentNode || scope)
        else if (node.querySelector && node.querySelector('[data-icon]')) inflateIcons(node)
      }
    }
  })
  observer.observe(scope, { childList: true, subtree: true })
  return observer
}

/** Phase-5 swap helper: register or override an icon path. */
export function registerIcon(name, svgPath) {
  _ICONS[name] = svgPath
}

/** Names of all registered icons (debug). */
export function listIcons() {
  return Object.keys(_ICONS).sort()
}
