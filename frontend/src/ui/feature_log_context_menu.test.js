import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createFeatureLogContextMenu } from './feature_log_context_menu.js'
import { initFeatureLogPanel } from './feature_log_panel.js'
import { showFeatureReorder, showFeatureSuppression } from './primitives/feature_reorder_dialog.js'
import { showFeatureDependencies } from './primitives/feature_dependencies_dialog.js'
vi.mock('./part_repair_panel.js', () => ({ initPartRepairPanel: vi.fn(), focusPartRepairRow: vi.fn() }))
vi.mock('./primitives/feature_reorder_dialog.js', () => ({ showFeatureReorder: vi.fn(), showFeatureSuppression: vi.fn() }))
vi.mock('./primitives/feature_dependencies_dialog.js', () => ({ showFeatureDependencies: vi.fn() }))

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', () => 1)
  document.body.innerHTML = '<div id="left-panel"><h2 id="feature-log-panel-heading"><span>History</span></h2>'
    + '<span id="feature-log-panel-arrow"></span><div id="feature-log-panel-body"></div></div>'
})
afterEach(() => {
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  document.body.innerHTML = ''; vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks()
})
function render(suppressed = false) {
  const source = { id: 'part', feature_log_cursor: -1, feature_log: [
    { id: 'first', feature_type: 'snapshot', op_kind: 'bundle-create', label: 'Bundle', suppressed },
    { id: 'second', feature_type: 'snapshot', op_kind: 'later', label: 'Later' },
  ], loadouts: [], cluster_transforms: [], deformations: [], overhangs: [] }
  const state = { currentDesign: source, assemblyActive: false }
  const subscriptions = {}
  const store = { getState: () => state, subscribeSlice: (key, fn) => { subscriptions[key] = fn; return () => {} } }
  const api = { partRepairAPI: {}, getFeatureDependencies: vi.fn().mockResolvedValue({ features: [] }) }
  initFeatureLogPanel(store, { api })
  const row = document.querySelector('#fl-list [data-fl-row="1"]')
  const open = () => { row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true })); vi.runAllTimers() }
  return { source, state, store, api, row, open, subscriptions }
}
const item = name => [...document.querySelectorAll('[role="menuitem"]')].find(el => el.textContent === name)

it.each([false, true])('moves secondary buttons into the row menu (suppressed=%s)', suppressed => {
  const f = render(suppressed)
  expect(f.row.querySelector('[title^="Move F"], [title^="Suppress F"], [title^="Unsuppress F"], [title$="dependencies"]')).toBeNull()
  f.open()
  expect([...document.querySelectorAll('[role="menuitem"]')].map(el => el.textContent))
    .toEqual([suppressed ? 'Unsuppress' : 'Suppress', 'Move…', 'View dependencies'])
  item(suppressed ? 'Unsuppress' : 'Suppress').click()
  expect(showFeatureSuppression).toHaveBeenCalledWith({ store: f.store, api: f.api, source: f.source, rowIndex: 0 })
  expect(document.querySelector('[role="menu"]')).toBeNull()
})
it('opens Move using the captured row and supports keyboard context menus', () => {
  const f = render()
  f.row.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true }))
  vi.runAllTimers()
  item('Move…').click()
  expect(showFeatureReorder).toHaveBeenCalledWith({ store: f.store, api: f.api, source: f.source, rowIndex: 0 })
})
it('opens dependencies and discards a reply after the document changes', async () => {
  const f = render()
  f.open(); item('View dependencies').click()
  await vi.waitFor(() => expect(showFeatureDependencies).toHaveBeenCalledOnce())
  showFeatureDependencies.mockClear()
  let resolve
  f.api.getFeatureDependencies.mockReturnValue(new Promise(done => { resolve = done }))
  f.open(); item('View dependencies').click()
  f.state.currentDesign = { id: 'other' }
  resolve({ features: [] })
  await Promise.resolve(); await Promise.resolve()
  expect(showFeatureDependencies).not.toHaveBeenCalled()
})
it('closes the menu on rebuild and prevents stale actions', () => {
  const f = render()
  f.open()
  f.state.currentDesign = { ...f.source, name: 'Updated' }
  item('Move…').click()
  expect(showFeatureReorder).not.toHaveBeenCalled()
  f.state.currentDesign = f.source
  f.open()
  f.subscriptions.design({ currentDesign: { ...f.source } }, { currentDesign: f.source })
  expect(document.querySelector('[role="menu"]')).toBeNull()
})

it('offers assembly suppression and move using the shared dialogs', () => {
  const source = { id: 'assembly', feature_log: [{ id: 'a', suppressed: true }, { id: 'b' }] }
  const row = document.createElement('div'); document.body.append(row)
  const store = { getState: () => ({ assemblyActive: true, currentAssembly: source }) }
  const api = { assemblyHistoryAPI: {} }
  const menu = createFeatureLogContextMenu({ store, api })
  menu.bind(row, source, 0, { assembly: true })
  expect(row.querySelector('[data-history-status="suppressed"]').textContent).toBe('Suppressed')
  row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }))
  vi.runAllTimers()
  item('Unsuppress').click()
  expect(showFeatureSuppression).toHaveBeenCalledWith({ store, api, source, rowIndex: 0, assembly: true })
  menu.close()
})

it('rejects a dependency response from another assembly revision', async () => {
  const { recordAssemblyResponse } = await import('../api/assembly_response_authority.js')
  const source = { id: 'assembly', feature_log: [{ id: 'a' }] }
  recordAssemblyResponse(source, { revision: 3 })
  const row = document.createElement('div'); document.body.append(row)
  const store = { getState: () => ({ assemblyActive: true, currentAssembly: source }) }
  const api = { getAssemblyFeatureDependencies: vi.fn(async () => ({ assembly_id: 'assembly', revision: 4, features: [] })) }
  const menu = createFeatureLogContextMenu({ store, api })
  menu.bind(row, source, 0, { assembly: true })
  row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true })); vi.runAllTimers()
  item('View dependencies').click()
  for (let i = 0; i < 10; ++i) await Promise.resolve()
  expect(showFeatureDependencies).not.toHaveBeenCalled()
  api.getAssemblyFeatureDependencies.mockResolvedValue({ assembly_id: 'assembly', revision: 3, features: [] })
  row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true })); vi.runAllTimers()
  item('View dependencies').click()
  for (let i = 0; i < 10; ++i) await Promise.resolve()
  expect(showFeatureDependencies).toHaveBeenCalledWith(expect.objectContaining({ assembly: true, source }))
  menu.close()
})
