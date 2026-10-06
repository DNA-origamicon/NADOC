import { afterEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createSelectionController } from '../scene/selection_controller.js'
import { initDeformationToolLauncher } from './deformation_tool_launcher.js'
let launcher
afterEach(() => { launcher?.cancel(); document.body.innerHTML = '' })
function setup() {
  document.body.innerHTML = '<canvas id="canvas"></canvas><div id="mode-indicator"></div>'
  const filters = { scaffold: false, overhangs: true }
  const store = createMockStore({ currentDesign: { id: 'part', helices: [{ id: 'h' }], cluster_transforms: [{ id: 'c', helix_ids: ['h'] }] }, selectableTypes: filters })
  const controller = createSelectionController({ store })
  const deps = { store, selectionManager: { clearSelection: controller.clear, setSelectionLevel: controller.setLevel }, showToast: vi.fn(), deformView: { isActive: () => true }, watchDeformState: vi.fn(), start: vi.fn(), exit: vi.fn(), setScope: vi.fn() }
  launcher = initDeformationToolLauncher(deps)
  return { ...deps, controller, filters }
}
it.each(['bend', 'twist'])('picks a fresh cluster before starting %s and restores Default', async type => {
  const d = setup()
  d.controller.replace([{ kind: 'cluster', id: 'c' }])
  launcher.open(type)
  expect(document.querySelector('.tool-picking-hint').textContent).toBe('Select a cluster')
  expect(d.start).not.toHaveBeenCalled()
  expect(d.store.getState().selection.level).toBe('cluster')
  d.controller.replace([{ kind: 'cluster', id: 'c' }]); await Promise.resolve()
  expect(d.store.getState().selection.level).toBe('default')
  expect(d.store.getState().selectableTypes).toEqual(d.filters)
  expect(d.store.getState().selection.items).toEqual([])
  expect(d.setScope).toHaveBeenCalledWith(['c'])
  expect(d.start).toHaveBeenCalledExactlyOnceWith(type)
  expect(d.watchDeformState).toHaveBeenCalledOnce()
  expect(document.querySelector('#deformation-cluster-picker')).toBeNull()
})
it('cancels a queued pick and cancels on document replacement', async () => {
  const d = setup()
  launcher.open('bend'); d.controller.replace([{ kind: 'cluster', id: 'c' }])
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await Promise.resolve()
  expect(d.start).not.toHaveBeenCalled()
  expect(d.store.getState().selection.level).toBe('default')
  launcher.open('twist'); d.store.setState({ currentDesign: { id: 'other' } }); await Promise.resolve()
  expect(document.querySelector('#deformation-cluster-picker')).toBeNull()
  expect(d.store.getState().selection.level).toBe('default')
})
it('replaces a pending tool without leaving a stale callback', async () => {
  const d = setup(); launcher.open('bend'); launcher.open('twist')
  d.controller.replace([{ kind: 'cluster', id: 'c' }]); await Promise.resolve()
  expect(d.start).toHaveBeenCalledExactlyOnceWith('twist')
})
