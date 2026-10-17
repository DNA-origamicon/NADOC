import { afterEach, expect, it, vi } from 'vitest'
import { initFeatureLogPanel } from './feature_log_panel.js'

afterEach(() => { window.dispatchEvent(new Event('nadoc:document-reset')); document.body.innerHTML = ''; vi.unstubAllGlobals() })
const tick = async () => { for (let i = 0; i < 6; i++) await Promise.resolve() }
function fixture({ enabled = true, cursor = -1, native = true, kind = 'nick' } = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }); vi.stubGlobal('requestAnimationFrame', () => 1)
  document.body.innerHTML = '<div id="left-panel"><h2 id="feature-log-panel-heading"><span>History</span></h2><span id="feature-log-panel-arrow"></span><div id="feature-log-panel-body"></div></div>'
  const child = { id: 'child', feature_type: 'minor', op_subtype: kind, label: 'Native nick', params: { helix_id: 'prefix-h', bp_index: 6, direction: 'FORWARD', ...(native ? { _proof_version: 1 } : {}) } }
  const parent = { id: 'parent', feature_type: 'routing-cluster', label: 'Fine Routing', evicted: true, diffs_evicted: true, children: [child] }
  const design = { id: 'part', feature_log_cursor: cursor, feature_log_sub_cursor: null, feature_log: [parent, { id: 'later', feature_type: 'snapshot', op_kind: 'manual', label: 'Later' }], loadouts: [], cluster_transforms: [], deformations: [], overhangs: [] }
  const context = { source: design, revision: 7 }, state = { currentDesign: design, assemblyActive: false }
  const api = { captureRoutingEditContext: vi.fn(() => context), isRoutingEditContextCurrent: vi.fn(() => true), editRoutingFeatureInputs: vi.fn(async () => null), editFeature: vi.fn(), seekFeatures: vi.fn(),
    getRoutingFeatureInputs: vi.fn(async () => ({ kind, params: child.params, prefix: { helices: [{ id: 'prefix-h', bp_start: 0, length_bp: 20 }], strands: [], crossovers: [], forced_ligations: [] }, source_design_id: 'part', source_revision: 7, feature_id: parent.id, child_id: child.id })) }
  initFeatureLogPanel({ getState: () => state, subscribeSlice: () => () => {} }, { api, routingHistoryEnabled: enabled })
  document.querySelector('[title="Expand Fine Routing"]').click()
  const edit = () => [...document.querySelectorAll('[data-fl-row="1.0"] button')].find(button => button.textContent === '✎')
  return { api, context, edit, state }
}

it('edits an evicted native child before a later feature through the actual panel and prefix form', async () => {
  const f = fixture(); expect(f.edit()?.disabled).toBe(false); f.edit().click(); await tick()
  expect(f.api.getRoutingFeatureInputs).toHaveBeenCalledWith(0, 0, f.context, 'parent', 'child')
  const bp = document.querySelector('[aria-label="Base index"]'); bp.value = '8'; bp.dispatchEvent(new Event('input'))
  ;[...document.querySelectorAll('button')].find(button => button.textContent === 'Apply').click(); await tick()
  expect(f.api.editRoutingFeatureInputs).toHaveBeenCalledWith(0, 0, expect.objectContaining({ bp_index: 8, _proof_version: 1 }), f.context, 'parent', 'child')
  expect(document.querySelector('[role="dialog"]')).not.toBeNull()
  expect(f.api.editFeature).not.toHaveBeenCalled(); expect(f.api.seekFeatures).not.toHaveBeenCalled()
})
it.each([{ enabled: false }, { native: false }, { kind: 'strand-delete' }])('does not manufacture native eligibility (%j)', options => {
  const f = fixture(options); expect(f.edit()).toBeUndefined(); expect(f.api.getRoutingFeatureInputs).not.toHaveBeenCalled()
})
it('requires latest history before loading a native child prefix', () => {
  const f = fixture({ cursor: 0 }); expect(f.edit().disabled).toBe(true); expect(f.api.getRoutingFeatureInputs).not.toHaveBeenCalled()
})
it('rejects a held prefix after reset without opening a stale editor', async () => {
  const f = fixture(); let finish
  f.api.getRoutingFeatureInputs.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  f.edit().click(); window.dispatchEvent(new Event('nadoc:document-reset')); f.api.isRoutingEditContextCurrent.mockReturnValue(false)
  finish({ kind: 'nick', params: { helix_id: 'stale', bp_index: 1, direction: 'FORWARD', _proof_version: 1 }, prefix: {} }); await tick()
  expect(document.querySelector('[aria-label="Base index"]')).toBeNull()
})
