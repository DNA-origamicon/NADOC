import { initPartComparisonViewer } from '../scene/part_comparison_viewer.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'

/** Inline private view: no nested modal, document store, or publication calls. */
export function createPartComparisonSurface({ host, controller, createViewer = initPartComparisonViewer }) {
  const root = el('section', { className: 'part-comparison', attrs: { 'aria-label': 'Private proposal comparison' } })
  const labels = el('div', { className: 'part-comparison__labels', children: [
    el('strong', { text: 'Published authored geometry · unverified' }), el('strong', { text: 'Evaluated proposal' })] })
  const basis = el('p', { className: 'part-repair__muted', text: 'All authored placements are shown. Physical and presentation layers are excluded. This coarse display does not qualify molecular changes.' })
  const status = el('p', { attrs: { role: 'status', 'aria-live': 'polite' } })
  const error = el('p', { className: 'part-repair__error', attrs: { role: 'alert' } })
  const assets = el('p', { className: 'part-repair__muted' })
  const canvasHost = el('div', { className: 'part-comparison__canvas' })
  let viewer = null, packet = null, disposed = false
  const fit = createButton({ label: 'Fit comparison', size: 'sm', onClick: () => viewer?.resetView() })
  const close = createButton({ label: 'Close comparison', size: 'sm', onClick: () => controller.close() })
  root.append(el('div', { className: 'part-repair__tools', children: [fit, close] }), basis, status, error, labels, canvasHost, assets)
  host.append(root)
  function clear() { viewer?.dispose(); viewer = null; packet = null; canvasHost.replaceChildren() }
  function render(state) {
    if (disposed) return
    root.hidden = !state.open
    if (!state.open || !state.projection) clear()
    status.textContent = state.busy ? 'Preparing private comparison…' : ''
    error.textContent = state.error?.message ?? ''
    assets.textContent = ''
    if (state.open && state.projection) {
      if (packet !== state.projection) {
        clear()
        try {
          viewer = createViewer(canvasHost, state.projection, state.binding)
          packet = state.projection
        } catch (failure) { clear(); error.textContent = failure.message ?? 'Comparison display unavailable' }
      }
      if (viewer) {
        const lists = [['Published', packet.published.unplaced_asset_ids], ['Proposed', packet.proposed.unplaced_asset_ids]]
        assets.textContent = lists.filter(([, ids]) => ids.length).map(([label, ids]) => `${label} unplaced assets: ${ids.join(', ')}`).join('. ')
      }
    }
    fit.disabled = !viewer
    labels.hidden = canvasHost.hidden = !viewer
  }
  const unsubscribe = controller.subscribe(render)
  return { dispose() {
    if (disposed) return
    disposed = true; unsubscribe(); clear(); root.remove()
  } }
}
