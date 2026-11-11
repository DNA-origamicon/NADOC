import './detached_sidebars.css'
import { enableSharedPanelStyles } from './shared_panel_views.js'
import { initDetachedOverlays } from './detached_overlays.js'
import { mountDetachedControlView } from './detached_control_view.js'

const layoutCSS = `
html, body { margin:0; width:100%; height:100%; overflow:hidden; }
body { display:flex; flex-direction:column; background:#0d1117; color:#e6edf3; }
#detached-close { position:fixed; top:5px; right:5px; z-index:99999; width:28px; height:28px; border:1px solid #484f58; border-radius:4px; background:#161b22; color:#e6edf3; cursor:pointer; }
#detached-workspace { display:flex; flex:1; min-height:0; gap:12px; }
.detached-side { display:flex; min-width:0; min-height:0; }
.detached-side[data-side=right] { flex-direction:row-reverse; }
.detached-columns { display:flex !important; flex-direction:row !important; flex:1 !important; min-width:0 !important; width:auto !important; height:100%; overflow:hidden; padding:0 !important; }
.detached-side[data-side=right] .detached-columns { flex-direction:row-reverse !important; }
.detached-columns .sidebar-column { flex:1 1 0 !important; width:0 !important; min-width:0; }
.detached-columns .sidebar-column-header { overflow:hidden; }
.detached-columns .sidebar-column-header span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.detached-columns .sidebar-column-body { overflow:auto; }
.detached-rail { display:flex; flex:none; width:40px; }
.detached-rail > div { height:100%; }
#left-tab-strip, #right-tab-strip { display:flex !important; padding-top:38px; }
#left-tab-toggle, #right-tab-toggle, .sidebar-column-resize, .sidebar-space-notice { display:none !important; }
#detached-closed { margin:auto; font-size:18px; }
#detached-workspace[hidden], #detached-closed[hidden] { display:none !important; }
`

/** One capability-bound child window per editor. No discovery, named-window
 * reuse, postMessage listener or cross-tab authority is involved. */
export function initDetachedSidebars({ store, left, right, document: doc = document,
  openWindow = (...args) => doc.defaultView.open(...args) } = {}) {
  const owner = doc.defaultView
  const trigger = doc.getElementById('menu-view-undock-sidebars')
  const stacks = { left, right }
  let child = null, childDoc = null, workspace, closedMessage, styleHost
  let rails = [], views = new Map(), sides = {}, closing = false, ownerGone = false
  let headObserver, panelObserver, closeTimer, overlays
  const active = () => !ownerGone && !!(store.getState().currentDesign || store.getState().assemblyActive)
  // Identity of both Window and Document must match. Navigation cannot retain
  // authority merely by occupying the popup's old window slot.
  function connected() {
    try { return child && !child.closed && child.document === childDoc } catch { return false }
  }
  const enabled = () => connected() && active()
  function clearViews() { for (const view of views.values()) view.dispose(); views.clear() }
  function render() {
    if (!connected()) return
    const alive = active()
    overlays?.refresh()
    workspace.hidden = !alive; closedMessage.hidden = alive
    if (!alive) { clearViews(); return }
    const wanted = new Set()
    for (const [side, stack] of Object.entries(stacks)) {
      const items = stack.isCollapsed() ? [] : stack.getInstances()
      sides[side].group.style.flex = `${items.length} 1 40px`
      for (const item of items) {
        const key = `${side}:${item.id}`; wanted.add(key)
        let view = views.get(key)
        if (!view) {
          const column = childDoc.createElement('section'); column.className = 'sidebar-column'
          column.dataset.panelType = item.type
          const header = childDoc.createElement('header'); header.className = 'sidebar-column-header'
          const title = childDoc.createElement('span')
          const close = childDoc.createElement('button'); close.className = 'sidebar-close'; close.textContent = '×'
          close.setAttribute('aria-label', `Close ${stack.getLabel(item.type)} sidebar`)
          close.onclick = () => { if (enabled()) stack.close(item.id) }
          const body = childDoc.createElement('div'); body.className = 'sidebar-column-body'
          header.append(title, close); column.append(header, body)
          sides[side].columns.append(column)
          const mirror = stack.mountDetached(item.type, body, { enabled })
          view = { title, dispose() { mirror.dispose(); column.remove() } }; views.set(key, view)
        }
        view.title.textContent = stack.getLabel(item.type)
      }
    }
    for (const [key, view] of views) if (!wanted.has(key)) { view.dispose(); views.delete(key) }
  }
  function syncStyles() {
    if (!connected()) return
    const sheets = [...doc.querySelectorAll('style, link[rel="stylesheet"]')]
    styleHost.replaceChildren(...sheets.map(sheet => {
      const copy = sheet.cloneNode(true)
      if (copy.tagName === 'LINK') copy.addEventListener('load', () => { if (connected()) enableSharedPanelStyles(childDoc) })
      // CSSOM edits (shared panel selectors) are not reflected in textContent.
      try { if (copy.tagName === 'STYLE' && sheet.sheet) copy.textContent = [...sheet.sheet.cssRules].map(rule => rule.cssText).join('\n') } catch {}
      return copy
    }))
    enableSharedPanelStyles(childDoc)
  }
  function release({ close = true } = {}) {
    if (closing) return
    closing = true
    const old = child
    overlays?.dispose(); overlays = null
    clearViews(); for (const rail of rails) rail.dispose(); rails = []
    headObserver?.disconnect(); panelObserver?.disconnect(); owner.clearInterval(closeTimer)
    child = null; childDoc = null; sides = {}
    doc.body.classList.remove('sidebars-undocked')
    for (const stack of Object.values(stacks)) stack.setDetached(false)
    trigger?.setAttribute('aria-pressed', 'false')
    if (close && old && !old.closed) old.close()
    owner.dispatchEvent(new owner.Event('resize'))
    closing = false
  }
  function toggle() {
    if (connected()) { release(); return }
    if (child) release({ close: false })
    const popup = openWindow('', '_blank', 'popup,width=1200,height=850')
    if (!popup) { owner.alert('Allow popups for this site to undock the sidebars.'); return }
    child = popup; childDoc = popup.document
    childDoc.title = `NADOC controls — ${owner.location.host}`
    const base = childDoc.createElement('base'); base.href = doc.baseURI
    styleHost = childDoc.createElement('div')
    const style = childDoc.createElement('style'); style.textContent = layoutCSS
    childDoc.head.replaceChildren(base, styleHost, style)
    const close = childDoc.createElement('button'); close.id = 'detached-close'; close.textContent = '×'
    close.setAttribute('aria-label', 'Close window'); close.title = 'Close window and dock sidebars'
    // Compile this static handler in the child document. Functions assigned by
    // the opener stop running after its realm is destroyed, even when bound.
    // pagehide below restores docking while the owner is still alive.
    close.setAttribute('onclick', 'window.close()')
    workspace = childDoc.createElement('main'); workspace.id = 'detached-workspace'
    closedMessage = childDoc.createElement('p'); closedMessage.id = 'detached-closed'; closedMessage.textContent = 'the session was closed'
    closedMessage.setAttribute('role', 'status')
    childDoc.body.replaceChildren(close, workspace, closedMessage)
    syncStyles()
    for (const [side, stack] of Object.entries(stacks)) {
      const group = childDoc.createElement('div'); group.className = 'detached-side'; group.dataset.side = side
      const rail = childDoc.createElement('div'); rail.className = 'detached-rail'
      const columns = childDoc.createElement('div'); columns.id = `${side}-panel`; columns.className = 'detached-columns'
      group.append(rail, columns); workspace.append(group); sides[side] = { group, columns }
      rails.push(mountDetachedControlView(doc.getElementById(`${side}-tab-strip`), rail, { enabled, preserveIds: true }))
    }
    // Set both flags before notifications cause a render.
    for (const stack of Object.values(stacks)) stack.setDetached(true)
    doc.body.classList.add('sidebars-undocked'); trigger?.setAttribute('aria-pressed', 'true')
    headObserver = new owner.MutationObserver(syncStyles)
    headObserver.observe(doc.head, { subtree: true, childList: true, characterData: true, attributes: true })
    panelObserver = new owner.MutationObserver(render)
    for (const side of ['left', 'right']) panelObserver.observe(doc.getElementById(`${side}-panel`), { attributes: true })
    popup.addEventListener('pagehide', () => { if (child === popup) release({ close: false }) }, { once: true })
    closeTimer = owner.setInterval(() => { if (!connected()) release({ close: false }) }, 500)
    overlays = initDetachedOverlays({ document: doc, target: childDoc.body, enabled })
    render(); owner.dispatchEvent(new owner.Event('resize')); popup.focus()
  }
  function ownerClosed() {
    ownerGone = true; render(); overlays?.dispose()
    for (const rail of rails) rail.dispose(); rails = []
    headObserver?.disconnect(); panelObserver?.disconnect(); owner.clearInterval(closeTimer)
  }
  const unsubscribe = store.subscribe(render)
  for (const side of ['left', 'right']) owner.addEventListener(`nadoc:${side}-tab-change`, render)
  owner.addEventListener('pagehide', ownerClosed)
  trigger?.addEventListener('click', toggle)
  return { toggle, dispose() {
    release(); unsubscribe(); trigger?.removeEventListener('click', toggle)
    for (const side of ['left', 'right']) owner.removeEventListener(`nadoc:${side}-tab-change`, render)
    owner.removeEventListener('pagehide', ownerClosed)
  } }
}
