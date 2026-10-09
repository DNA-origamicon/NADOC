import { el } from './primitives/dom.js'
import './tool_popup.css'
import './tool_sections.css'

/** Non-modal CAD tool window. Reparents the actual controls, preserving handlers. */
export function createToolPopup({ panel, title, onClose, panelDisplay = 'block' }) {
  if (!panel) return null
  const heading = panel.querySelector(':scope > h2') ?? el('h2', { text: title })
  heading.id ||= `${panel.id}-title`
  const close = el('button', { className: 'btn btn--ghost btn--sm', text: '×', attrs: { type: 'button', 'aria-label': `Close ${title}` }, on: { click: () => onClose?.() } })
  const header = el('div', { className: 'tool-popup__header', children: [heading, close] })
  const content = el('div', { className: 'tool-popup__content', children: [panel] })
  const root = el('section', { className: 'tool-popup', attrs: { role: 'dialog', 'aria-modal': 'false', 'aria-labelledby': heading.id }, children: [header, content] })
  root.dataset.toolPanel = panel.id
  root.style.display = 'none'
  document.body.append(root)
  let position = null, drag = null
  const canvas = document.getElementById('canvas')
  function layout() {
    const bounds = canvas?.getBoundingClientRect()
    const left = Math.max(8, bounds?.left ?? 8), top = Math.max(8, bounds?.top ?? 8)
    const right = Math.min(window.innerWidth - 8, bounds?.right || window.innerWidth - 8)
    const bottom = Math.min(window.innerHeight - 8, bounds?.bottom || window.innerHeight - 8)
    const width = Math.max(1, right - left), height = Math.max(1, bottom - top)
    root.style.width = `${Math.min(360, width)}px`
    root.style.maxHeight = `${height}px`
    const rect = root.getBoundingClientRect()
    position ??= { x: left + 12, y: top + 12 }
    position.x = Math.max(left, Math.min(position.x, right - rect.width))
    position.y = Math.max(top, Math.min(position.y, bottom - rect.height))
    root.style.left = `${position.x}px`; root.style.top = `${position.y}px`
  }
  const sync = () => {
    const visible = panel.style.display !== 'none' && !panel.hidden
    root.style.display = visible ? 'flex' : 'none'
    if (visible) layout()
  }
  const observer = new MutationObserver(sync)
  observer.observe(panel, { attributes: true, attributeFilter: ['style', 'hidden'] })
  const resize = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => { if (root.style.display !== 'none') layout() }) : null
  if (canvas) resize?.observe(canvas)
  resize?.observe(panel)
  window.addEventListener('resize', layout)
  header.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('button, input, select')) return
    event.preventDefault()
    const rect = root.getBoundingClientRect()
    drag = { x: event.clientX - rect.left, y: event.clientY - rect.top }
    header.setPointerCapture(event.pointerId)
  })
  header.addEventListener('pointermove', event => {
    if (!drag) return
    position = { x: event.clientX - drag.x, y: event.clientY - drag.y }
    layout()
  })
  const endDrag = () => { drag = null }
  header.addEventListener('pointerup', event => { if (header.hasPointerCapture(event.pointerId)) header.releasePointerCapture(event.pointerId); endDrag() })
  header.addEventListener('pointercancel', endDrag)
  header.addEventListener('lostpointercapture', endDrag)
  root.addEventListener('pointerdown', () => {
    for (const popup of document.querySelectorAll('.tool-popup')) popup.style.zIndex = popup === root ? '121' : '120'
  })
  sync()
  return {
    root,
    show() { panel.style.display = panelDisplay; sync() },
    hide() { panel.style.display = 'none'; sync() },
    setTitle(value) { heading.textContent = value; close.setAttribute('aria-label', `Close ${value}`) },
    dispose() { observer.disconnect(); resize?.disconnect(); window.removeEventListener('resize', layout); root.remove() },
  }
}
