/** Keep metrics available without occupying the guest toolbar. */
export function mountViewerShortcuts({ document: doc = document, performancePanel }) {
  const keydown = event => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 'p') return
    event.preventDefault()
    if (!performancePanel.open) performancePanel.showModal()
  }
  doc.addEventListener('keydown', keydown)
  return () => doc.removeEventListener('keydown', keydown)
}
