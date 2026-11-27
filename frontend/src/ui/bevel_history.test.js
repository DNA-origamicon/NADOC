// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { initFeatureLogPanel } from './feature_log_panel.js'

afterEach(() => { document.body.replaceChildren(); vi.unstubAllGlobals() })
it('opens an earlier native Bevel even when recovery snapshots were evicted', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', () => 1)
  document.body.innerHTML = '<div id="left-panel"><h2 id="feature-log-panel-heading"><span>History</span></h2><span id="feature-log-panel-arrow"></span><div id="feature-log-panel-body"></div></div>'
  const entry = { id: 'bevel-1', feature_type: 'snapshot', op_kind: 'bevel', label: 'Bevel', evicted: true,
    params: { _proof_version: 1, operation_id: 'op-1', angle_deg: 30, direction_deg: 15, position_bp: 84, cluster_id: 'c' } }
  const state = { currentDesign: { id: 'part', feature_log_cursor: -1, feature_log: [entry,
    { ...entry, id: 'bevel-2', params: { ...entry.params, operation_id: 'op-2' } }],
    loadouts: [], cluster_transforms: [], deformations: [], overhangs: [] }, assemblyActive: false }
  const editBevel = vi.fn()
  initFeatureLogPanel({ getState: () => state, subscribeSlice: () => () => {} }, { api: {}, onEditBevel: editBevel })
  const button = document.querySelector('#fl-list [data-fl-row="1"] [title="Edit Bevel parameters"]')
  expect(button).not.toBeNull(); expect(button.disabled).toBe(false)
  button.click(); await Promise.resolve()
  expect(editBevel).toHaveBeenCalledWith(entry, 0)
})
