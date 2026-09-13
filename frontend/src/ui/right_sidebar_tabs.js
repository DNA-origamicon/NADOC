import { initSidebarStack } from './sidebar_stack.js'

const TAB_SECTIONS = {
  assembly: ['assembly-panel'],
  properties: ['properties-section', 'dimensions-section', 'reverse-complement-section', 'primitives-panel', 'overhang-orient-panel', 'move-rotate-panel', 'extrude-panel', 'deform-panel', 'strand-hist-section', 'groups-panel'],
  visualization: ['representation-modes-section', 'view-volumes-section', 'coloring-options-section', 'repr-options-section', 'right-view-actions', 'right-multi-view', 'right-multi-overlay'],
  clustering: ['cluster-panel', 'joints-panel'],
  overhangs: ['overhang-panel', 'overhang-connections-section', 'assembly-overhang-panel', 'assembly-oconn-panel', 'strand-anim-panel'],
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

export function initRightSidebarTabs({ document, storage = globalThis.localStorage, getAvailableWidth = null } = {}) {
  const panel = document?.getElementById('right-panel')
  const strip = document?.getElementById('right-tab-strip')
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

  const changeListeners = new Set()
  const stack = initSidebarStack({
    side: 'right', document, storage, getAvailableWidth,
    labels: { assembly: 'Assembly', properties: 'Properties', visualization: 'Visualization', clustering: 'Clustering', overhangs: 'Overhangs' },
    panePrefix: 'right-tab-content-', defaultTab: 'properties',
    storageKey: 'nadoc.rightSidebar.v2', legacyKeys: ['nadoc.rightSidebar.v1'],
    onChange(detail) { for (const listener of changeListeners) listener(detail) },
  })
  function setAssemblyMode(enabled) {
    const button = strip.querySelector('[data-tab="assembly"]')
    if (button) button.hidden = !enabled
    if (enabled) stack.selectTab('assembly')
    else {
      for (const item of stack.getInstances()) if (item.type === 'assembly') stack.close(item.id)
      if (stack.getActiveTab() === 'assembly') stack.selectTab('properties')
    }
  }

  // These contextual tools previously lived outside the tab panes. Keep them
  // in Properties and reveal that column when a tool explicitly becomes visible.
  const contextual = ['primitives-panel', 'overhang-orient-panel'].map(id => document.getElementById(id)).filter(Boolean)
  const visible = new Map(contextual.map(node => [node, node.style.display !== 'none']))
  const toolObserver = new MutationObserver(() => {
    for (const node of contextual) {
      const shown = node.style.display !== 'none'
      if (shown && !visible.get(node)) stack.selectTab('properties')
      visible.set(node, shown)
    }
  })
  for (const node of contextual) toolObserver.observe(node, { attributes: true, attributeFilter: ['style'] })

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

  return {
    ...stack, select: stack.setActiveTab, open: stack.selectTab, setAssemblyMode, render: stack.refresh,
    onChange(listener) {
      changeListeners.add(listener)
      return () => changeListeners.delete(listener)
    },
    dispose() { changeListeners.clear(); observer.disconnect(); toolObserver.disconnect(); stack.dispose() },
  }
}
