import { mountDetachedControlView } from './detached_control_view.js'

/** Dialogs and context menus opened by sidebar actions retain their original
 * controllers, while also appearing in the controls window. */
export function initDetachedOverlays({ document: doc, target, enabled }) {
  const views = new Map()
  const selector = '.modal__overlay, dialog[open], [role="dialog"], .context-menu, [role="listbox"], .pose-thumbnail, #op-progress.visible, #overhangs-manager-modal, #assembly-overhangs-manager-modal'
  let disposed = false
  function refresh() {
    if (disposed) return
    const candidates = enabled() ? [...doc.querySelectorAll(selector)].filter(node =>
      !node.closest('#left-panel, #right-panel') && !node.hidden && doc.defaultView.getComputedStyle(node).display !== 'none') : []
    const roots = candidates.filter(node => !candidates.some(parent => parent !== node && parent.contains(node)))
    for (const [node, view] of views) if (!roots.includes(node)) { view.dispose(); views.delete(node) }
    for (const node of roots) {
      if (views.has(node)) continue
      const host = target.ownerDocument.createElement('div')
      host.className = 'detached-overlay'; target.append(host)
      const mirror = mountDetachedControlView(node, host, { enabled })
      views.set(node, { dispose() { mirror.dispose(); host.remove() } })
    }
  }
  const observer = new doc.defaultView.MutationObserver(refresh)
  observer.observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class', 'hidden', 'open'] })
  refresh()
  return { refresh, dispose() {
    disposed = true; observer.disconnect()
    for (const view of views.values()) view.dispose()
    views.clear()
  } }
}
