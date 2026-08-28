/** Canonical order for the cards inside every simulation-engine panel. */
export const SIMULATION_CARD_ORDER = [
  'Jobs', 'Clusters', 'Advanced', 'Anchors', 'Electric field', 'Hard surface',
  'Visualizations', 'Graphs and Metrics', 'Export trajectory', 'Health', 'Details',
]

const rank = title => {
  const normalized = String(title || '').trim()
  const exact = SIMULATION_CARD_ORDER.indexOf(normalized)
  if (exact >= 0) return exact
  if (normalized.startsWith('Advanced')) return SIMULATION_CARD_ORDER.indexOf('Advanced')
  return SIMULATION_CARD_ORDER.length
}

/** Reorder direct child cards while preserving their live nodes and non-card siblings. */
export function standardizeSimulationCardOrder(panelBody) {
  if (!panelBody) return []
  const cards = [...panelBody.children].filter(child => child.classList?.contains('ox-card'))
  const ordered = cards.map((card, index) => ({
    card, index,
    title: card.querySelector(':scope > .ox-card__header .ox-card__title')?.textContent || '',
  })).sort((a, b) => rank(a.title) - rank(b.title) || a.index - b.index)

  const slots = cards.map(() => document.createComment('simulation-card-slot'))
  cards.forEach((card, index) => card.replaceWith(slots[index]))
  slots.forEach((slot, index) => slot.replaceWith(ordered[index].card))
  return ordered.map(entry => entry.title.trim())
}
