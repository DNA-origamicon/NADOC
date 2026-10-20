import { afterEach, expect, it } from 'vitest'
import { createMockStore } from '../../test-helpers/mock_store.js'
import { showFeatureDependencies } from './feature_dependencies_dialog.js'

afterEach(() => { document.body.innerHTML = '' })
const graph = { complete: true, features: [
  { id: 'base', row_index: 0, label: 'Extrude', parents: [], children: ['bend'] },
  { id: 'bend', row_index: 1, label: 'Bend', parents: ['base'], children: ['nick'], conservative: true },
  { id: 'nick', row_index: 2, label: 'Output nick', parents: ['bend'], children: [] },
] }
it('shows parents and downstream routing children without changing the part', () => {
  const source = { id: 'part' }, store = createMockStore({ currentDesign: source })
  const modal = showFeatureDependencies({ graph, rowIndex: 1, store, source })
  expect(document.querySelector('[aria-label="Parents"]').textContent).toContain('F1: Extrude')
  expect(document.querySelector('[aria-label="Dependents"]').textContent).toContain('F3: Output nick')
  expect(document.body.textContent).toContain('conservative ordering dependencies')
  expect(store.getState().currentDesign).toBe(source)
  modal.close()
})
it('closes the graph when its source is replaced even with the same design ID', () => {
  const source = { id: 'part' }, store = createMockStore({ currentDesign: source })
  showFeatureDependencies({ graph, rowIndex: 1, store, source })
  expect(document.querySelector('[role="dialog"]')).not.toBeNull()
  store.setState({ currentDesign: { id: 'part' } })
  expect(document.querySelector('[role="dialog"]')).toBeNull()
})
it('aggregates routing children without showing their internal edges as external parents', () => {
  const source = { id: 'part' }, store = createMockStore({ currentDesign: source })
  const grouped = { ...graph, features: graph.features.map(row => ({ ...row,
    row_index: row.id === 'nick' ? 1 : row.row_index })) }
  const modal = showFeatureDependencies({ graph: grouped, rowIndex: 1, store, source })
  expect(document.querySelector('[aria-label="Parents"]').textContent).toBe('ParentsF1: Extrude')
  expect(document.querySelector('[aria-label="Dependents"]').textContent).toBe('DependentsNone')
  modal.close()
})
