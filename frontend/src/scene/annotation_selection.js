/** Transient editor selection shared by the sidebar and viewport, never saved. */
export function createAnnotationSelection({ document, container, pane, controller }) {
  let selected = null
  const listeners = new Set()
  const select = (id, source = 'sidebar') => {
    if (id && !controller.get(id)) id = null
    const changed = id !== selected
    selected = id
    for (const card of pane.querySelectorAll('.anno-card')) {
      card.classList.toggle('is-selected', card.dataset.annotationId === id)
    }
    if (id && source === 'viewport') {
      const card = [...pane.querySelectorAll('.anno-card')].find(node => node.dataset.annotationId === id)
      if (!card?.getClientRects().length) document.defaultView?.__rightSidebar?.selectTab('annotations')
      card?.scrollIntoView?.({ block: 'nearest' })
    }
    if (changed) for (const fn of listeners) fn(id)
  }
  const interact = event => {
    const target = event.target.closest?.('[data-annotation-id]')
    const inSidebar = target && (pane.contains(target) || target.closest('.sidebar-column[data-panel-type="annotations"]'))
    if (target && (inSidebar || container.contains(target))) {
      select(target.dataset.annotationId, inSidebar ? 'sidebar' : 'viewport')
    } else select(null)
  }
  document.addEventListener('pointerdown', interact, true)
  document.addEventListener('focusin', interact)
  const off = controller.subscribe(() => { if (selected && !controller.get(selected)) select(null) })
  return {
    get: () => selected, select,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    dispose() { off(); listeners.clear(); document.removeEventListener('pointerdown', interact, true); document.removeEventListener('focusin', interact) },
  }
}
