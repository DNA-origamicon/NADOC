// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createSelectionController } from '../scene/selection_controller.js'
import { initCornerTool } from './corner_tool.js'

let tool
afterEach(() => { tool?.dispose(); vi.useRealTimers(); document.body.replaceChildren() })
function setup() {
  vi.useFakeTimers()
  document.body.innerHTML = '<button id="menu-tools-corner">Corner</button>'
  const design = { id: 'part', lattice_type: 'SQUARE', helices: [{ id: 'h', bp_start: 0, length_bp: 168 }],
    cluster_transforms: [{ id: 'c', name: 'Bundle', helix_ids: ['h'] }] }
  const store = createMockStore({ currentDesign: design })
  const selection = createSelectionController({ store })
  const preview = { guide: vi.fn(), full: vi.fn(), clear: vi.fn(), dispose: vi.fn() }
  const requests = []
  const calculate = vi.fn((source, parameters, options) => {
    requests.push({ source, parameters, ...options })
    return new Promise(() => {})
  })
  const commit = vi.fn(async () => {}), showToast = vi.fn()
  tool = initCornerTool({ store, selectionManager: { clearSelection: selection.clear, setSelectionLevel: selection.setLevel },
    makePreview: () => preview, designRenderer: {}, showToast, calculate, commit,
    capture: () => ({ docId: 'doc', expected_design_id: 'part', expected_revision: 3 }) })
  return { store, selection, preview, requests, commit, showToast }
}
async function selected(d) {
  document.getElementById('menu-tools-corner').click()
  expect(d.store.getState().selection.level).toBe('cluster')
  d.selection.replace([{ kind: 'cluster', id: 'c' }])
  await Promise.resolve(); await vi.advanceTimersByTimeAsync(100)
  expect(d.store.getState().selection.level).toBe('default')
}
it('requires the source part owner instead of using a stale part behind an assembly', () => {
  const d = setup()
  d.store.setState({ assemblyActive: true })
  document.getElementById('menu-tools-corner').click()
  expect(d.requests).toHaveLength(0)
  expect(document.getElementById('corner-panel').style.display).toBe('none')
  expect(d.showToast.mock.calls[0][0]).toMatch(/source part/)
})
it('picks a cluster, shows cylinder then Full preview and commits the frozen source', async () => {
  const d = setup(); await selected(d)
  const request = d.requests[0]
  expect(request.parameters).toEqual({ cluster_id: 'c', position_bp: 84, angle_deg: 90, direction_deg: 0 })
  request.onEvent({ type: 'guide', guide: { cuts: [] } })
  expect(d.preview.guide).toHaveBeenCalledWith({ cuts: [] })
  request.onEvent({ type: 'progress', percent: 50, stage: 'Calculating seams', remaining_seconds: .4 })
  expect(document.querySelector('[role=status]').textContent).toContain('50%')
  request.onEvent({ type: 'ready', candidate: { geometry: 'full' } })
  expect(d.preview.full).toHaveBeenCalledWith({ geometry: 'full' })
  document.querySelector('.def-btn.primary').click()
  await Promise.resolve()
  expect(d.commit).toHaveBeenCalledWith(request.source, request.parameters)
  expect(request.signal.aborted).toBe(true)
})
it('aborts stale previews, ignores late Full results, and releases everything on document change', async () => {
  const d = setup(); await selected(d)
  const stale = d.requests[0]
  const field = document.getElementById('corner-angleDeg')
  field.value = '75'; field.dispatchEvent(new Event('input'))
  expect(stale.signal.aborted).toBe(true)
  stale.onEvent({ type: 'ready', candidate: {} })
  expect(d.preview.full).not.toHaveBeenCalled()
  expect(document.querySelector('.def-btn.primary').disabled).toBe(true)
  await vi.advanceTimersByTimeAsync(100)
  expect(d.requests[1].parameters.angle_deg).toBe(75)
  d.store.setState({ currentDesign: { id: 'other' } })
  expect(d.requests[1].signal.aborted).toBe(true)
  expect(d.preview.clear).toHaveBeenCalled()
})

it('edits a recorded Corner by feature identity without selecting or creating another corner', async () => {
  const d = setup()
  const entry = { id: 'feature-1', feature_type: 'snapshot', op_kind: 'corner',
    params: { _proof_version: 1, operation_id: 'corner-op', cluster_id: 'c',
      position_bp: 56, angle_deg: 75, direction_deg: 30 } }
  d.store.setState({ currentDesign: { ...d.store.getState().currentDesign, feature_log: [entry] } })
  tool.openEdit(entry)
  expect(document.querySelector('.tool-popup__header h2').textContent).toBe('Edit Corner')
  expect(document.getElementById('corner-angleDeg').value).toBe('75')
  expect([...document.querySelectorAll('button')].find(node => node.textContent === 'Change selection').hidden).toBe(true)
  await vi.advanceTimersByTimeAsync(100)
  const request = d.requests[0]
  expect(request.source.featureId).toBe('feature-1')
  expect(request.parameters).toEqual({ cluster_id: 'c', position_bp: 56, angle_deg: 75, direction_deg: 30 })
  request.onEvent({ type: 'ready', candidate: {} })
  let complete
  d.commit.mockImplementation(() => new Promise(resolve => { complete = resolve }))
  document.querySelector('.def-btn.primary').click()
  expect(document.querySelector('fieldset').disabled).toBe(true)
  expect(d.commit).toHaveBeenCalledWith(request.source, request.parameters)
  d.store.setState({ currentDesign: { id: 'other' } })
  expect(document.getElementById('corner-panel').style.display).toBe('none')
  complete(); await Promise.resolve()
  expect(document.getElementById('corner-panel').style.display).toBe('none')
})
