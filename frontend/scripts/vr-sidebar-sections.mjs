/** Extract desktop card identities and ancestry without confusing repeated titles. */
export function sidebarSections(pane, key, clean) {
  const cards = new Map()
  for (const [index, element] of [...(pane?.querySelectorAll('.panel-section, .ox-card, details, fieldset') || [])].entries()) {
    const heading = [...element.children].find(child => child.matches('.ox-card__header, h2, h3, summary, legend'))
    if (!heading) continue
    const title = heading.querySelector('.ox-card__title') || heading
    const copy = title.cloneNode(true)
    copy.querySelectorAll('button,input,select,.icon,[id$="-arrow"]').forEach(node => node.remove())
    const label = clean(copy.textContent).replace(/^[▸▾▶▼+−–—\s]+/, '').trim()
    if (!label) continue
    const identity = heading.id || element.id || element.querySelector('[id]')?.id || `card-${index}`
    cards.set(element, { id: `section:${key}:${identity}`, label, heading })
  }
  const parents = element => {
    const result = []
    for (let node = element.parentElement; node && node !== pane; node = node.parentElement) {
      if (cards.has(node)) result.unshift(cards.get(node).id)
    }
    return result
  }
  const headings = new Map()
  for (const [element, card] of cards) {
    headings.set(card.heading, { id: card.id, label: card.label, section: '', kind: 'section',
      options: [], action: card.id, parents: parents(element), source: 'frontend/index.html', reason: '' })
  }
  return { headings, parents }
}
