import { createSelectionController } from '../scene/selection_controller.js'

/** Row gestures use displayed order and the same canonical refs as 3D picks. */
export function wireSpreadsheetRowSelection({ tbody, store }) {
  const selection = createSelectionController({ store })
  let anchor = null, applying = false
  const rowFor = event => {
    if (event.target.closest('input, button, select, textarea, a, [contenteditable="true"]')) return null
    const row = event.target.closest('tr[data-strand-id]')
    return row?.parentElement === tbody ? row : null
  }
  // Shift gestures should select rows, not browser text across the table.
  tbody.addEventListener('mousedown', event => {
    if (event.button === 0 && (event.shiftKey || event.ctrlKey || event.metaKey) && rowFor(event)) event.preventDefault()
  })
  tbody.addEventListener('click', event => {
    const row = rowFor(event)
    if (!row || event.button !== 0 || selection.getState().context !== 'design') return
    const id = row.dataset.strandId, additive = event.ctrlKey || event.metaKey
    const ids = [...tbody.children].filter(row => !row.hidden && row.style.display !== 'none').map(row => row.dataset.strandId)
    const start = ids.indexOf(anchor), end = ids.indexOf(id)
    if (end < 0) return
    const range = event.shiftKey && start >= 0
    // Keep the anchor for repeated Shift clicks; any non-range pick establishes it.
    if (!range) anchor = id
    applying = true
    try {
      if (range) {
        const refs = ids.slice(Math.min(start, end), Math.max(start, end) + 1)
          .filter(sid => sid !== id).concat(id).map(id => ({ kind: 'strand', id }))
        // Clicked endpoint is primary, including backward ranges.
        if (additive) selection.extend(refs)
        else selection.replace(refs)
      } else if (additive) selection.toggle({ kind: 'strand', id })
      else selection.replace([{ kind: 'strand', id }])
    } finally { applying = false }
  })
  store.subscribe((next, prev) => {
    if (next.currentDesign?.id !== prev.currentDesign?.id || (next.selection?.context ?? 'design') !== (prev.selection?.context ?? 'design')) anchor = null
  })
  // Selection from the table must not scroll back to the first selected row.
  return { isApplying: () => applying }
}
