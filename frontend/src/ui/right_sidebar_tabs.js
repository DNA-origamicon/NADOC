const TAB_SECTIONS = {
  properties: ['properties-section', 'reverse-complement-section', 'move-rotate-panel', 'extrude-panel', 'deform-panel', 'strand-hist-section', 'groups-panel'],
  visualization: ['representation-modes-section', 'repr-options-section', 'right-view-actions', 'right-multi-view', 'right-multi-overlay'],
  clustering: ['cluster-panel', 'joints-panel'],
  overhangs: ['overhang-panel', 'overhang-connections-section', 'strand-anim-panel'],
}

const REPRESENTATIONS = [
  ['Hull Prism', 'menu-view-hull-prism'],
  ['Cylinders', 'menu-view-detail-cylinders'],
  ['Beads', 'menu-view-detail-beads'],
  ['Full', 'menu-view-detail-full'],
  ['Surface', 'menu-view-surface'],
  ['VDW / Space-fill', 'menu-view-atomistic-vdw'],
  ['Ball & Stick', 'menu-view-atomistic-ballstick'],
  ['Stick', 'menu-view-atomistic-stick'],
  ['mrDNA Coarse', 'menu-view-mrdna-coarse'],
  ['mrDNA Fine', 'menu-view-mrdna-fine'],
  ['oxDNA', 'menu-view-oxdna'],
]

function makeSection(document, id, title, body) {
  const section = document.createElement('div')
  section.id = id
  section.className = 'panel-section ox-card'
  const heading = document.createElement('h2')
  heading.textContent = title
  section.append(heading, body)
  return section
}

function buildAddedSections(document) {
  const modesBody = document.createElement('div')
  modesBody.id = 'right-representation-modes'
  modesBody.className = 'ox-card__body'
  for (const [label, targetId] of REPRESENTATIONS) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'xover-mode-btn right-repr-btn'
    button.textContent = label
    button.dataset.target = targetId
    button.addEventListener('click', () => document.getElementById(targetId)?.click())
    modesBody.append(button)
  }
  const representations = makeSection(document, 'representation-modes-section', 'Representations', modesBody)

  const actionsBody = document.createElement('div')
  actionsBody.className = 'ox-card__body'
  actionsBody.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:6px'
  const actions = makeSection(document, 'right-view-actions', 'View Actions', actionsBody)

  const multiViewBody = document.createElement('div')
  multiViewBody.id = 'right-multi-view-body'
  multiViewBody.className = 'ox-card__body'
  const multiView = makeSection(document, 'right-multi-view', 'Multi-view', multiViewBody)

  const multiOverlayBody = document.createElement('div')
  multiOverlayBody.id = 'right-multi-overlay-body'
  multiOverlayBody.className = 'ox-card__body'
  const multiOverlay = makeSection(document, 'right-multi-overlay', 'Multi-overlay', multiOverlayBody)

  return { representations, actionsBody, actions, multiView, multiOverlay }
}

export function initRightSidebarTabs({ document, storage = globalThis.localStorage } = {}) {
  const panel = document?.getElementById('right-panel')
  const strip = document?.getElementById('right-tab-strip')
  const toggle = document?.getElementById('right-tab-toggle')
  if (!panel || !strip) return null

  const added = buildAddedSections(document)
  panel.append(added.representations, added.actions, added.multiView, added.multiOverlay)
  for (const id of ['reset-btn', 'unhide-all-btn']) {
    const button = document.getElementById(id)
    if (button) added.actionsBody.append(button)
  }

  for (const [tab, ids] of Object.entries(TAB_SECTIONS)) {
    const pane = document.getElementById(`right-tab-content-${tab}`)
    for (const id of ids) {
      const section = document.getElementById(id)
      if (!pane || !section) continue
      if (section.classList.contains('panel-section')) section.classList.add('ox-card')
      pane.append(section)
    }
  }

  const buttons = [...strip.querySelectorAll('.right-tab-btn')]
  const tabs = buttons.map(button => button.dataset.tab)
  let activeTab = 'properties'
  let collapsed = false
  try {
    const raw = storage?.getItem('nadoc.rightSidebar.v1')
    const saved = raw?.startsWith('{') ? JSON.parse(raw) : { activeTab: raw }
    if (tabs.includes(saved?.activeTab)) activeTab = saved.activeTab
    if (typeof saved?.collapsed === 'boolean') collapsed = saved.collapsed
  } catch { /* storage may be unavailable */ }

  function persist() {
    try { storage?.setItem('nadoc.rightSidebar.v1', JSON.stringify({ activeTab, collapsed })) } catch { /* storage may be unavailable */ }
  }

  function render() {
    const shut = collapsed || panel.classList.contains('locked-inactive')
    panel.classList.toggle('hidden', shut)
    for (const button of buttons) button.classList.toggle('active', button.dataset.tab === activeTab && !shut)
    for (const name of tabs) {
      const pane = document.getElementById(`right-tab-content-${name}`)
      if (pane) pane.hidden = name !== activeTab
    }
    if (toggle) {
      toggle.textContent = shut ? '◀' : '▶'
      toggle.title = shut ? 'Show sidebar' : 'Hide sidebar'
    }
  }

  function select(tab) {
    if (!tabs.includes(tab)) return
    if (tab === activeTab && !collapsed) collapsed = true
    else { activeTab = tab; collapsed = false }
    persist()
    render()
  }

  // Tool-driven navigation must reveal a tab without inheriting the tab button's
  // click-again-to-collapse behaviour.  Panels such as Extrude use this when they
  // become active so their controls are always visible.
  function open(tab) {
    if (!tabs.includes(tab)) return
    activeTab = tab
    collapsed = false
    persist()
    render()
  }
  for (const button of buttons) button.addEventListener('click', () => select(button.dataset.tab))
  toggle?.addEventListener('click', () => {
    collapsed = !collapsed
    persist()
    render()
  })
  render()

  const updateRepresentation = () => {
    for (const button of document.querySelectorAll('.right-repr-btn')) {
      const target = document.getElementById(button.dataset.target)
      button.classList.toggle('active', target?.classList.contains('is-checked'))
    }
  }
  const observer = new MutationObserver(updateRepresentation)
  for (const [, targetId] of REPRESENTATIONS) {
    const target = document.getElementById(targetId)
    if (target) observer.observe(target, { attributes: true, attributeFilter: ['class'] })
  }
  updateRepresentation()

  return { select, open, render, getActiveTab: () => activeTab, isCollapsed: () => collapsed, dispose: () => observer.disconnect() }
}
