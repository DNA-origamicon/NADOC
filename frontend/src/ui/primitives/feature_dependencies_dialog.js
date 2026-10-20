import { createModal } from './modal.js'
import { createButton } from './button.js'
import { el } from './dom.js'

/** Inspect saved-input relationships without replaying or changing the part. */
export function showFeatureDependencies({ graph, rowIndex, store, source }) {
  const selected = graph.features.filter(feature => feature.row_index === rowIndex)
  if (!selected.length) throw new Error('This feature has no dependency information.')
  const ids = new Set(selected.map(feature => feature.id))
  const body = el('div')
  for (const [key, title] of [['parents', 'Parents'], ['children', 'Dependents']]) {
    const related = new Set(selected.flatMap(feature => feature[key]).filter(id => !ids.has(id)))
    const section = el('section', { attrs: { 'aria-label': title } })
    section.append(el('h3', { text: title }))
    const list = el('ul')
    for (const feature of graph.features.filter(feature => related.has(feature.id)))
      list.append(el('li', { text: `F${feature.row_index + 1}: ${feature.label}` }))
    section.append(related.size ? list : el('p', { text: 'None' }))
    body.append(section)
  }
  if (!graph.complete || graph.features.some(feature => feature.conservative))
    body.append(el('p', { text: 'Includes conservative ordering dependencies. Editing or deleting a feature checks the actual downstream regeneration.' }))
  let unsubscribe = null
  const modal = createModal({ title: `F${rowIndex + 1} dependencies`, size: 'sm', body,
    actions: [createButton({ label: 'Close', onClick: () => modal.close() })],
    onClose: () => { unsubscribe?.(); unsubscribe = null },
  })
  modal.root.setAttribute('aria-label', `F${rowIndex + 1} dependencies`)
  modal.open()
  unsubscribe = store.subscribe?.(next => {
    if (next.currentDesign !== source || next.assemblyActive) modal.close()
  })
  return modal
}
