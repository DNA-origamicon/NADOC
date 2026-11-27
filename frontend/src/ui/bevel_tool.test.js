// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createSelectionController } from '../scene/selection_controller.js'
import { initBevelTool } from './bevel_tool.js'

let tool
const data = { component: {}, paths: [{ helix_id: 'h', bps: [0, 84, 167], points: [[0, 0, 0], [0, 0, 28], [0, 0, 56]], tangents: [[0, 0, 1], [0, 0, 1], [0, 0, 1]], rights: [[1, 0, 0], [1, 0, 0], [1, 0, 0]] }] }
afterEach(() => { tool?.dispose(); document.body.replaceChildren() })
function setup(options = {}) {
  document.body.innerHTML = '<button id="menu-tools-bevel">Bevel</button>'
  const design = { id: 'part', lattice_type: 'SQUARE', helices: [{ id: 'h', bp_start: 0, length_bp: 168 }],
    strands: [{ domains: [{ helix_id: 'h', start_bp: 0, end_bp: 167 }] }],
    cluster_transforms: [{ id: 'c', name: 'Bundle', helix_ids: ['h'] }] }
  const store = createMockStore({ currentDesign: design }), selection = createSelectionController({ store })
  const preview = { full: vi.fn(), mask: vi.fn(), clear: vi.fn(), dispose: vi.fn() }
  const plane = { update: vi.fn(), clear: vi.fn(), dispose: vi.fn() }
  const loadSource = vi.fn(async () => data)
  const commit = vi.fn(async () => {}), showToast = vi.fn()
  tool = initBevelTool({ store, selectionManager: { clearSelection: selection.clear, setSelectionLevel: selection.setLevel },
    makePreview: () => preview, makePlane: () => plane, designRenderer: {}, showToast, commit, loadSource,
    capture: () => ({ docId: 'doc', expected_design_id: 'part', expected_revision: 3 }), holdSaves: () => null, ...options })
  return { store, selection, preview, plane, loadSource, commit, showToast }
}
async function selected(d) {
  document.getElementById('menu-tools-bevel').click()
  d.selection.replace([{ kind: 'cluster', id: 'c' }])
  await Promise.resolve(); await Promise.resolve()
}
const apply = () => document.querySelector('.def-btn.primary')
it('loads Full once and changes the local mask immediately without server requests', async () => {
  const d = setup(); await selected(d)
  expect(d.preview.full).toHaveBeenCalledOnce()
  expect(apply().disabled).toBe(false)
  const field = document.getElementById('bevel-angleDeg')
  field.value = '25'; field.dispatchEvent(new Event('input'))
  expect(d.preview.mask).toHaveBeenCalledTimes(2)
  expect(d.loadSource).toHaveBeenCalledOnce()
  apply().click(); await Promise.resolve(); await Promise.resolve()
  await vi.waitFor(() => expect(d.commit).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ angle_deg: 25 })))
})
it('ignores late source geometry and restores the display after a document change', async () => {
  let resolve
  const d = setup({ loadSource: () => new Promise(r => { resolve = r }) }); await selected(d)
  d.store.setState({ currentDesign: { id: 'other' } })
  resolve(data); await Promise.resolve()
  expect(d.preview.full).not.toHaveBeenCalled(); expect(d.preview.clear).toHaveBeenCalled()
  expect(d.plane.clear).toHaveBeenCalled()
})
it('ignores a late commit completion after document reset', async () => {
  let finish
  const commit = vi.fn(() => new Promise(r => { finish = r }))
  const d = setup({ commit })
  await selected(d); apply().click()
  window.dispatchEvent(new Event('nadoc:document-reset')); finish(); await Promise.resolve(); await Promise.resolve()
  expect(commit).toHaveBeenCalledOnce()
  expect(document.getElementById('bevel-panel').style.display).toBe('none')
})
it('loads the recorded input prefix for a native history edit', async () => {
  const d = setup(), entry = { id: 'feature', feature_type: 'snapshot', op_kind: 'bevel', params: {
    _proof_version: 2, operation_id: 'op', cluster_id: 'c', position_bp: 84, angle_deg: 15, direction_deg: 0, trim_end: 'end' } }
  d.store.setState({ currentDesign: { ...d.store.getState().currentDesign, feature_log: [entry] } })
  tool.openEdit(entry); await Promise.resolve()
  expect(d.loadSource).toHaveBeenCalledWith(expect.objectContaining({ featureId: 'feature' }), expect.anything(), expect.anything())
  expect(document.querySelector('.tool-popup__header h2').textContent).toBe('Edit Bevel')
})
it('blocks Apply when the plane would remove nothing, but permits recovery', async () => {
  const d = setup(); await selected(d)
  const field = document.getElementById('bevel-positionBp')
  field.value = '167'; field.dispatchEvent(new Event('input'))
  expect(apply().disabled).toBe(true)
  field.value = '84'; field.dispatchEvent(new Event('input'))
  expect(apply().disabled).toBe(false); expect(d.loadSource).toHaveBeenCalledOnce()
})
it('drains and releases an in-flight save without capturing its stale source', async () => {
  let saved
  const release = vi.fn(), d = setup({ holdSaves: () => ({ ready: new Promise(r => { saved = r }), release }) })
  document.getElementById('menu-tools-bevel').click()
  expect(d.loadSource).not.toHaveBeenCalled()
  d.store.setState({ currentDesign: { ...d.store.getState().currentDesign } })
  saved(); await Promise.resolve()
  d.selection.replace([{ kind: 'cluster', id: 'c' }]); await Promise.resolve()
  expect(d.loadSource).toHaveBeenCalledOnce()
  tool.cancel(); expect(release).toHaveBeenCalledOnce()
})
it('requires source-part topology ownership in assembly mode', () => {
  const d = setup(); d.store.setState({ assemblyActive: true }); tool.open()
  expect(d.loadSource).not.toHaveBeenCalled(); expect(d.showToast).toHaveBeenCalled()
})

it('reuses loaded native geometry and requests only axis data for a new cut', async () => {
  const loadSource = vi.fn(async () => ({ paths: data.paths, component: null }))
  const d = setup({ loadSource })
  d.store.setState({ currentGeometry: [{ helix_id: 'h', bp_index: 84 }],
    currentHelixAxes: { h: { start: [0, 0, 0], end: [0, 0, 56], samples: [[0, 0, 0], [0, 0, 56]] } } })
  await selected(d)
  expect(loadSource).toHaveBeenCalledWith(expect.anything(), expect.anything(), expect.objectContaining({ includeGeometry: false }))
  expect(d.preview.full).toHaveBeenCalledWith(expect.objectContaining({ helix_axes: [expect.objectContaining({ helix_id: 'h' })],
    nucleotides: d.store.getState().currentGeometry }))
})
