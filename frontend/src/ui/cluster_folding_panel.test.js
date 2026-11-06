// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { foldingPlan, foldingPlanText } from './cluster_folding_order.js'
import { initClusterFoldingPanel } from './cluster_folding_panel.js'

const design = { id: 'part', cluster_transforms: [
  { id: 'c1', name: 'Cluster 1' }, { id: 'c2', name: 'Cluster 2', folding_order: 1 },
  { id: 'c3', name: 'Cluster 3', folding_order: 2 },
] }
let panel
afterEach(() => { panel?.destroy(); localStorage.clear(); document.body.replaceChildren() })
function setup(api = {}) {
  document.body.innerHTML = '<div id="cluster-folding-panel"></div>'
  const store = createMockStore({ currentDesign: structuredClone(design), assemblyActive: false })
  api.patchCluster ??= vi.fn(async (id, fields) => {
    const next = structuredClone(store.getState().currentDesign)
    Object.assign(next.cluster_transforms.find(c => c.id === id), fields)
    store.setState({ currentDesign: next })
    return { design: next }
  })
  panel = initClusterFoldingPanel({ store, api })
  return { store, api }
}
const input = id => document.querySelector(`[data-folding-cluster="${id}"]`)
async function change(id, value) {
  input(id).value = value
  input(id).dispatchEvent(new Event('change'))
  await vi.waitFor(() => expect(input(id).disabled).toBe(false))
}
it('orders stages numerically, retains ties, and leaves unassigned clusters outside the order', () => {
  const d = structuredClone(design)
  d.cluster_transforms.push({ id: 'c4', name: 'Cluster 4', folding_order: 1 })
  expect(foldingPlan(d).stages.map(s => [s.stage, s.clusters.map(c => c.id)])).toEqual([[1, ['c2', 'c4']], [2, ['c3']]])
  expect(foldingPlanText(d)).toBe('Stage 1: Cluster 2, Cluster 4 → Stage 2: Cluster 3\nUndefined — default routing: Cluster 1.')
  expect(foldingPlanText(null)).toBe('No folding stages assigned.')
})
it('assigns and clears through the recorded API, and updates the preview from the accepted design', async () => {
  const { api, store } = setup()
  expect(input('c1').value).toBe('')
  await change('c3', '1')
  expect(api.patchCluster).toHaveBeenCalledWith('c3', { folding_order: 1 })
  expect(document.querySelector('.folding-plan').textContent).toContain('Stage 1: Cluster 2, Cluster 3')
  await change('c2', '')
  expect(api.patchCluster).toHaveBeenLastCalledWith('c2', { folding_order: null })
  store.setState({ currentDesign: structuredClone(design) }) // undo/reload
  expect(input('c2').value).toBe('1')
})
it('rejects fractional and out-of-range stages without a request', async () => {
  const { api } = setup()
  for (const value of ['0', '1.5', '1000']) await change('c1', value)
  expect(api.patchCluster).not.toHaveBeenCalled()
  expect(document.querySelector('[role=alert]').textContent).toContain('whole stage')
})
it('restores the accepted stage and exposes a failed save', async () => {
  setup({ patchCluster: vi.fn(async () => { throw new Error('Document is read-only') }) })
  await change('c2', '3')
  expect(input('c2').value).toBe('1')
  expect(document.querySelector('[role=alert]').textContent).toContain('Document is read-only')
})
it('persists collapse and switches documents without leaking assignments', () => {
  const { store } = setup()
  document.querySelector('.folding-heading').click()
  expect(document.querySelector('#cluster-folding-body').hidden).toBe(true)
  panel.destroy(); panel = initClusterFoldingPanel({ store, api: {} })
  expect(document.querySelector('.folding-heading').getAttribute('aria-expanded')).toBe('false')
  store.setState({ currentDesign: { id: 'other', cluster_transforms: [{ id: 'c2', name: 'Other' }] } })
  expect(input('c2').value).toBe('')
  store.setState({ assemblyActive: true })
  expect(input('c2')).toBeNull()
  expect(document.body.textContent).toContain('Open a part for editing')
})
