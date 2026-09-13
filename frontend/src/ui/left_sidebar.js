import { initSidebarStack } from './sidebar_stack.js'

export function initLeftSidebar({ store, photoMode, getAvailableWidth = null }) {
  const controller = initSidebarStack({
    side: 'left', labels: { 'feature-log': 'Feature log', dynamics: 'Simulations', scene: 'Animation', photo: 'Appearance', plates: 'Plates & tubes' },
    panePrefix: 'tab-content-', defaultTab: 'feature-log', defaultCollapsed: true,
    storageKey: 'nadoc.leftSidebar.v3', legacyKeys: ['nadoc.leftSidebar.v2', 'nadoc.leftSidebar.v1'], getAvailableWidth,
    titleSuffix: type => type === 'photo' ? (photoMode?.mode?.isActive?.() ? ' · On' : ' · Off') : '',
    onChange({ collapsed, openPanels }) {
      const simulationControlsOpen = !collapsed && openPanels.includes('dynamics')
      if (store.getState().simulationControlsOpen !== simulationControlsOpen) store.setState({ simulationControlsOpen })
    },
  })
  if (!controller) return null
  const lightingChanged = () => controller.refresh()
  window.addEventListener('nadoc:lighting-change', lightingChanged)
  const dispose = controller.dispose
  return Object.assign(controller, {
    collapseForTeardown() { photoMode?.exit?.(); controller.refresh() },
    maxRightWidth: controller.maxOppositeWidth,
    dispose() { window.removeEventListener('nadoc:lighting-change', lightingChanged); dispose() },
  })
}
