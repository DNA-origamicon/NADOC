import './cluster_folding_panel.css'
import { el } from './primitives/dom.js'
import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { foldingPlanText } from './cluster_folding_order.js'

export function initClusterFoldingPanel({ store, api }) {
  const root = document.getElementById('cluster-folding-panel')
  if (!root) return { destroy() {} }
  let disposed = false, pending = false
  const heading = el('button', { className: 'folding-heading', text: 'Folding Order', attrs: {
    type: 'button', 'aria-label': 'Folding Order', 'aria-expanded': String(!getSectionCollapsed('clustering', root.id)), 'aria-controls': 'cluster-folding-body',
  } })
  const content = el('div', { id: 'cluster-folding-body' })
  content.hidden = getSectionCollapsed('clustering', root.id)
  heading.addEventListener('click', () => {
    content.hidden = !content.hidden
    heading.setAttribute('aria-expanded', String(!content.hidden))
    setSectionCollapsed('clustering', root.id, content.hidden)
  })
  root.replaceChildren(el('h2', { children: [heading] }), content)
  function render() {
    if (disposed) return
    const state = store.getState(), design = state.currentDesign
    content.replaceChildren()
    if (state.assemblyActive) {
      content.append(el('p', { className: 'tool-help', text: 'Folding orders are part-level objectives for the part autostapler. Open a part for editing to assign its cluster stages. Assembly-wide folding and polymerized staples need a separate routing objective.' }))
      return
    }
    const clusters = design?.cluster_transforms ?? []
    if (!clusters.length) {
      content.append(el('p', { className: 'tool-help', text: design ? 'Create clusters to assign a folding order.' : 'Open a part to assign a folding order.' }))
      return
    }
    content.append(el('p', { className: 'tool-help', text: 'Lower stages target earlier folding; equal stages share a priority. Undefined keeps default staple routing. Assignments are saved with the part and can be undone.' }))
    const error = el('p', { className: 'folding-error', attrs: { role: 'alert' } })
    for (const cluster of clusters) {
      const input = el('input', { className: 'input', attrs: { type: 'number', min: 1, max: 999, step: 1,
        placeholder: 'Undefined', 'aria-label': `Folding stage for ${cluster.name || cluster.id}`, disabled: pending },
      dataset: { foldingCluster: cluster.id } })
      input.value = cluster.folding_order ?? ''
      input.addEventListener('change', async () => {
        if (!input.checkValidity()) { error.textContent = 'Use a whole stage from 1 to 999, or leave blank for Undefined.'; return }
        error.textContent = ''
        const value = input.value === '' ? null : Number(input.value)
        if (value === (cluster.folding_order ?? null)) return
        if (pending || store.getState().currentDesign !== design || store.getState().assemblyActive) { render(); return }
        pending = true
        content.querySelectorAll('input').forEach(node => { node.disabled = true })
        error.textContent = ''
        try {
          if (!await api.patchCluster(cluster.id, { folding_order: value })) {
            throw new Error(store.getState().lastError?.message ?? 'The assignment was refused.')
          }
        } catch (cause) {
          if (!disposed && store.getState().currentDesign === design) {
            input.value = cluster.folding_order ?? ''
            error.textContent = `Could not save folding stage: ${cause.message}`
          }
        } finally {
          pending = false
          if (!disposed) content.querySelectorAll('input').forEach(node => { node.disabled = false })
        }
      })
      content.append(el('label', { className: 'folding-row', children: [el('span', { text: cluster.name || cluster.id }), input] }))
    }
    content.append(error, el('p', { className: 'folding-plan', text: foldingPlanText(design) }),
      el('p', { className: 'tool-help', text: 'Use this plan in Experimental autostaple to target higher median staple folding temperatures in earlier stages. Undefined keeps default routing.' }))
  }
  const unsubscribe = store.subscribe((next, prev) => {
    if (next.currentDesign !== prev.currentDesign || next.assemblyActive !== prev.assemblyActive) render()
  })
  render()
  return { destroy() { disposed = true; unsubscribe(); root.replaceChildren() } }
}
