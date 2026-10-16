import { afterEach, expect, it, vi } from 'vitest'
import { initFeatureLogPanel } from './feature_log_panel.js'

afterEach(() => { window.dispatchEvent(new Event('nadoc:document-reset')); document.body.innerHTML = ''; vi.unstubAllGlobals() })
function fixture({ kind = 'extrude-segment', native = true, cursor = -1, subCursor = null } = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }); vi.stubGlobal('requestAnimationFrame', () => 1)
  document.body.innerHTML = '<div id="left-panel"><div class="tab-content"><h2 id="feature-log-panel-heading"><span>Feature Log</span></h2><span id="feature-log-panel-arrow"></span><div id="feature-log-panel-body"></div></div></div>'
  const params = { cells: [[0, 0]], length_bp: 21, plane: 'XY', offset_nm: 0, strand_filter: 'both', ligate_adjacent: true,
    separate_fresh_extrusions: true, history_seed: 'saved', ...(native ? { _proof_version: 1 } : {}),
    ...(kind === 'circle-segment' ? { cell_lengths: [21] } : {}),
    ...(kind === 'extrude-frame' ? { name: 'Frame', translation_nm: [0, 0, 0], rotation_xyzw: [0, 0, 0, 1], source_frame_id: null, source_legacy_plane: false } : {}),
  }
  const entry = { id: 'stable-feature', feature_type: 'snapshot', op_kind: kind, label: 'Extrusion', evicted: true, params }
  const state = { currentDesign: { id: 'part', feature_log_cursor: cursor, feature_log_sub_cursor: subCursor,
    feature_log: [entry, { id: 'later', feature_type: 'snapshot', op_kind: 'manual', label: 'Later', params: {} }],
    loadouts: [{ id: 'main', name: 'Main' }], active_loadout_id: 'main', cluster_transforms: [], deformations: [], overhangs: [] },
  currentAssembly: null, assemblyActive: false }
  const context = { designId: 'part', revision: 10 }
  const api = { captureFeatureEditContext: vi.fn(() => context), isFeatureEditContextCurrent: vi.fn(() => true),
    editNativeExtrusionFeature: vi.fn(async () => null), editFeature: vi.fn() }
  initFeatureLogPanel({ getState: () => state, subscribeSlice: () => () => {} }, { api })
  const edit = () => [...document.querySelectorAll('#fl-list [data-fl-row="1"] button')].find(node => node.textContent === '✎')
  return { api, context, edit }
}
it.each(['extrude-segment', 'circle-segment', 'extrude-frame'])('opens native %s despite evicted bodies and later snapshots using stable input identity', async kind => {
  const f = fixture({ kind }); expect(f.edit()).toBeDefined(); expect(f.edit().disabled).toBe(false); f.edit().click()
  expect(f.api.captureFeatureEditContext).toHaveBeenCalledTimes(1)
  const input = document.querySelector(`[aria-label="${kind === 'circle-segment' ? 'Cell 1 length (bp)' : 'Length (bp)'}"]`)
  input.value = '28'; input.dispatchEvent(new Event('input'))
  const save = [...document.querySelectorAll('button')].find(node => node.textContent === 'Save')
  save.click(); await Promise.resolve(); await Promise.resolve()
  expect(f.api.editNativeExtrusionFeature).toHaveBeenCalledWith(0, expect.objectContaining({ history_seed: 'saved', _proof_version: 1 }), f.context, 'stable-feature')
  expect(f.api.editFeature).not.toHaveBeenCalled(); expect(document.querySelector('[role="dialog"]')).not.toBeNull()
})
it.each([{ cursor: -2 }, { cursor: 0 }, { cursor: -1, subCursor: 0 }])('requires latest cursor before opening native history input editor (%j)', options => {
  const f = fixture(options); expect(f.edit()).toBeDefined(); expect(f.edit().disabled).toBe(true)
  expect(f.api.captureFeatureEditContext).not.toHaveBeenCalled()
})
it('preserves legacy evicted-row restriction', () => {
  expect(fixture({ native: false }).edit()).toBeUndefined()
})
