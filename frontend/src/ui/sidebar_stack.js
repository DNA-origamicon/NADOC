import './sidebar_stack.css'
/** Shared-state columns for either edge of the workspace. */
import { createSharedPanelViews, enableSharedPanelStyles } from './shared_panel_views.js'
import { sidebarBudget, fitSidebarWidths, MIN_SIDEBAR_WIDTH, DEFAULT_SIDEBAR_WIDTH, MAX_SIDEBAR_WIDTH, MIN_WORKSPACE_WIDTH } from './sidebar_stack_layout.js'

export function initSidebarStack({ side, labels, panePrefix, defaultTab, defaultCollapsed = false,
  storage = globalThis.localStorage, storageKey, legacyKeys = [], getAvailableWidth = null,
  onChange = () => {}, titleSuffix = () => '', document = globalThis.document }) {
  const window = document.defaultView
  const ids = Object.keys(labels)
  const panel = document.getElementById(`${side}-panel`)
  const strip = document.getElementById(`${side}-tab-strip`)
  if (!panel || !strip) return null
  const main = document.getElementById('main-area')
  const opposite = document.getElementById(`${side === 'left' ? 'right' : 'left'}-panel`)
  const oppositeStrip = document.getElementById(`${side === 'left' ? 'right' : 'left'}-tab-strip`)
  const panes = Object.fromEntries(ids.map(id => [id, document.getElementById(`${panePrefix}${id}`)]))
  const buttons = Object.fromEntries(ids.map(id => [id, strip.querySelector(`[data-tab="${id}"]`)]))
  const toggle = document.getElementById(`${side}-tab-toggle`)
  const locked = () => panel.classList.contains(side === 'left' ? 'locked-hidden' : 'locked-inactive')
  const allowed = type => ids.includes(type) && !buttons[type]?.hidden
  const parking = document.createElement('div')
  parking.hidden = true
  parking.className = 'sidebar-parking'
  panel.append(parking)
  for (const pane of Object.values(panes)) if (pane) { parking.append(pane); pane.hidden = true }
  panel.classList.add('sidebar-stack')
  panel.style.width = ''
  // Width belongs to each column; the former whole-sidebar handle is obsolete.
  strip.querySelector(`[data-resize="${side}"]`)?.remove()
  enableSharedPanelStyles(document)
  const shared = Object.fromEntries(ids.filter(id => panes[id]).map(id => [id, createSharedPanelViews(panes[id], parking)]))
  const notice = document.createElement('div')
  notice.className = 'sidebar-space-notice'
  notice.setAttribute('role', 'status')
  notice.hidden = true
  strip.append(notice)
  let noticeTimer = null
  let activeTab = defaultTab
  let collapsed = defaultCollapsed
  let serial = 0
  let instances = []
  let savedInstances = [{ type: defaultTab, width: DEFAULT_SIDEBAR_WIDTH }]
  try {
    const raw = [storageKey, ...legacyKeys].map(key => storage?.getItem(key)).find(Boolean)
    const saved = raw ? (raw.startsWith('{') ? JSON.parse(raw) : { activeTab: raw }) : null
    if (saved) {
      if (allowed(saved.activeTab)) activeTab = saved.activeTab
      if (typeof saved.collapsed === 'boolean') collapsed = saved.collapsed
      savedInstances = (saved.instances || (saved.openPanels || [activeTab]).map(type => ({ type, width: DEFAULT_SIDEBAR_WIDTH })))
        .filter(item => allowed(item.type))
      if (!savedInstances.length && !saved.instances) savedInstances = [{ type: defaultTab, width: DEFAULT_SIDEBAR_WIDTH }]
    }
  } catch { /* Ignore corrupt preferences. */ }

  const width = element => element?.getBoundingClientRect().width || 0
  const budget = () => getAvailableWidth?.() ?? sidebarBudget(width(main) || window.innerWidth, width(opposite), width(strip) + width(oppositeStrip))
  const total = () => instances.reduce((sum, item) => sum + item.width, 0)
  function inform(message) {
    notice.textContent = message
    notice.hidden = false
    clearTimeout(noticeTimer)
    noticeTimer = setTimeout(() => { notice.hidden = true }, 5000)
  }
  function persist() {
    try { storage?.setItem(storageKey, JSON.stringify({ activeTab, collapsed, instances: instances.map(({ type, width }) => ({ type, width })) })) } catch {}
  }
  function render() {
    const shut = collapsed || !instances.length || locked()
    panel.classList.toggle('hidden', shut)
    for (const id of ids) {
      const count = instances.filter(item => item.type === id).length
      buttons[id]?.classList.toggle('active', count > 0 && !shut)
      buttons[id]?.setAttribute('aria-label', `Open another ${labels[id]} sidebar`)
      if (buttons[id]) buttons[id].title = `${labels[id]} — open another sidebar (${count} open)`
    }
    for (const item of instances) {
      item.el.style.width = `${item.width}px`
      item.title.textContent = labels[item.type] + titleSuffix(item.type)
    }
    if (toggle) {
      toggle.textContent = (shut === (side === 'left')) ? '▶' : '◀'
      toggle.title = shut ? 'Show controls' : 'Hide controls'
      toggle.setAttribute('aria-expanded', String(!shut))
    }
  }
  function changed() {
    render(); persist()
    window.dispatchEvent(new window.CustomEvent(`nadoc:${side}-tab-change`, {
      detail: { activeTab, collapsed, openPanels: instances.map(item => item.type), navigationOnly: true },
    }))
    onChange({ activeTab, collapsed: collapsed || !instances.length || locked(), openPanels: instances.map(item => item.type) })
  }
  function close(instanceId, notify = true) {
    const item = instances.find(item => item.id === instanceId)
    if (!item) return
    item.view.dispose()
    item.cleanResize()
    item.el.remove()
    instances = instances.filter(other => other !== item)
    if (notify) changed()
  }
  function resize(item, requested) {
    item.width = Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, budget() - total() + item.width, requested))
    render()
  }
  function wireResize(item, handle) {
    let start = null
    const down = event => {
      if (event.button !== 0) return
      start = { x: event.clientX, width: item.width }
      handle.setPointerCapture?.(event.pointerId)
      handle.classList.add('is-dragging')
      event.preventDefault()
    }
    const move = event => { if (start) resize(item, start.width + (event.clientX - start.x) * (side === 'left' ? 1 : -1)) }
    const end = () => { if (start) { start = null; handle.classList.remove('is-dragging'); persist() } }
    const keydown = event => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
      event.preventDefault()
      resize(item, item.width + (event.key === 'ArrowRight' ? 20 : -20) * (side === 'left' ? 1 : -1)); persist()
    }
    handle.addEventListener('pointerdown', down)
    handle.addEventListener('keydown', keydown)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
    }
  }
  function add(type, requested = DEFAULT_SIDEBAR_WIDTH, notify = true) {
    if (!shared[type] || !allowed(type)) return false
    const remaining = budget() - total()
    if (remaining < MIN_SIDEBAR_WIDTH) {
      if (notify) inform('No room for another sidebar. Close or narrow a panel first.')
      return false
    }
    const el = document.createElement('section')
    el.className = 'sidebar-column'
    el.dataset.panelType = type
    el.dataset.sidebarInstance = String(++serial)
    el.setAttribute('aria-label', `${labels[type]} sidebar`)
    const header = document.createElement('header')
    header.className = 'sidebar-column-header'
    const title = document.createElement('span')
    const x = document.createElement('button')
    x.type = 'button'; x.textContent = '×'; x.className = 'sidebar-close'
    x.setAttribute('aria-label', `Close ${labels[type]} sidebar`)
    header.append(title, x)
    const body = document.createElement('div')
    body.className = 'sidebar-column-body'
    const handle = document.createElement('div')
    handle.className = 'sidebar-column-resize'
    handle.tabIndex = 0
    handle.setAttribute('role', 'separator')
    handle.setAttribute('aria-orientation', 'vertical')
    handle.setAttribute('aria-label', `Resize ${labels[type]} sidebar`)
    el.append(header, body, handle)
    panel.append(el)
    const item = { id: serial, type, width: Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, remaining, Number(requested) || DEFAULT_SIDEBAR_WIDTH)), el, title, view: shared[type].mount(body) }
    item.cleanResize = wireResize(item, handle)
    x.addEventListener('click', () => close(item.id))
    instances.push(item)
    activeTab = type
    if (notify) { collapsed = false; changed() }
    return true
  }
  function reconcile() {
    const fitted = fitSidebarWidths(instances.map(item => item.width), budget())
    const removed = instances.slice(fitted.length)
    for (const item of removed) close(item.id, false)
    instances.forEach((item, i) => { item.width = fitted[i] })
    if (removed.length) inform('Some sidebars were closed to keep the workspace visible.')
    changed()
  }
  function setActiveTab(type) {
    if (locked()) return false
    return add(type)
  }
  // Navigation from existing commands focuses a current view; rail clicks add copies.
  function selectTab(type) {
    if (!allowed(type) || locked()) return false
    const item = instances.find(item => item.type === type)
    if (item) { activeTab = type; collapsed = false; item.view.activate(); reconcile(); return true }
    return add(type)
  }
  function toggleCollapsed() {
    if (locked()) return
    collapsed = !collapsed
    if (!collapsed && !instances.length) add(activeTab, DEFAULT_SIDEBAR_WIDTH, false)
    reconcile()
  }
  for (const item of savedInstances) add(item.type, item.width, false)
  for (const id of ids) buttons[id]?.addEventListener('click', () => setActiveTab(id))
  toggle?.addEventListener('click', toggleCollapsed)
  window.addEventListener('resize', reconcile)
  const observer = typeof window.ResizeObserver === 'function' ? new window.ResizeObserver(reconcile) : null
  if (main) observer?.observe(main)
  if (opposite) observer?.observe(opposite)
  const controller = {
    setActiveTab, selectTab, toggleCollapsed, close,
    getActiveTab: () => activeTab,
    getOpenPanels: () => instances.map(item => item.type),
    getInstances: () => instances.map(({ id, type, width }) => ({ id, type, width })),
    isCollapsed: () => collapsed,
    maxOppositeWidth: () => (width(main) || window.innerWidth) - width(strip) - width(oppositeStrip) - MIN_WORKSPACE_WIDTH - (collapsed ? 0 : total()),
    refresh: changed,
    dispose() {
      observer?.disconnect(); clearTimeout(noticeTimer)
      window.removeEventListener('resize', reconcile)
      for (const item of [...instances]) close(item.id, false)
      for (const view of Object.values(shared)) view.dispose()
    },
  }
  window[`__${side}Sidebar`] = controller
  changed()
  return controller
}
