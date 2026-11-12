import './visualization_cards.css'
import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'

/** Keep live controls in place so shared sidebar copies retain their handlers. */
export function initVisualizationCards({ document, getCollapsed = getSectionCollapsed, setCollapsed = setSectionCollapsed }) {
  const cleanup = []
  for (const id of ['representation-modes-section', 'coloring-options-section', 'right-view-actions']) {
    const card = document.getElementById(id), heading = card?.querySelector(':scope > h2')
    if (!heading) continue
    const body = heading.nextElementSibling
    if (!body) continue
    card.classList.add('visualization-card')
    if (id === 'right-view-actions') card.classList.add('view-actions-card')
    body.classList.add('visualization-card-body')
    body.id ||= `${id}-body`
    const button = document.createElement('button')
    button.type = 'button'; button.className = 'visualization-card-toggle'
    button.textContent = heading.textContent
    button.setAttribute('aria-label', heading.textContent)
    button.setAttribute('aria-controls', body.id)
    heading.replaceChildren(button)
    function render(collapsed) {
      body.hidden = collapsed
      button.setAttribute('aria-expanded', String(!collapsed))
    }
    render(getCollapsed('visualization', id, false))
    const toggle = () => { render(!body.hidden); setCollapsed('visualization', id, body.hidden) }
    button.addEventListener('click', toggle)
    cleanup.push(() => button.removeEventListener('click', toggle))
  }
  return () => cleanup.forEach(dispose => dispose())
}
