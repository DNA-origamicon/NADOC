import { afterEach, expect, it, vi } from 'vitest'
import { initFeatureLogPanel } from './feature_log_panel.js'

afterEach(() => {
  window.dispatchEvent(new Event('nadoc:document-reset'))
  document.body.innerHTML = ''; vi.unstubAllGlobals()
})

function fixture({ enabled = true, cursor = -1, subCursor = null, version = 1, evicted = true } = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', () => 1)
  document.body.innerHTML = '<div id="left-panel"><div class="tab-content"><h2 id="feature-log-panel-heading"><span>Feature Log</span></h2><span id="feature-log-panel-arrow"></span><div id="feature-log-panel-body"></div></div></div>'
  const entry = { id: 'original-sweep-feature', feature_type: 'snapshot', op_kind: 'sweep', label: 'Sweep', evicted,
    params: { _proof_version: version, sweep_id: '05f1ca4f-9ffa-4d6d-bdc2-2f59da59862f',
      cells: [[0, 0]], points_nm: [[0, 0, 0], [0, 0, 5]], plane: 'XY' } }
  const state = { currentDesign: { id: 'part', feature_log_cursor: cursor, feature_log_sub_cursor: subCursor,
    feature_log: [entry, { id: 'later', feature_type: 'snapshot', op_kind: 'manual', label: 'Later', params: {} }],
    loadouts: [{ id: 'main', name: 'Main' }], active_loadout_id: 'main',
    cluster_transforms: [], deformations: [], overhangs: [] }, assemblyActive: false, currentAssembly: null }
  const api = { editFeature: vi.fn() }, onEditSweep = vi.fn()
  initFeatureLogPanel({ getState: () => state, subscribeSlice: () => () => {} }, {
    api, onEditSweep, sweepHistoryEnabled: enabled,
  })
  const edit = [...document.querySelectorAll('#fl-list [data-fl-row="1"] button')]
    .find(button => button.textContent === '✎')
  return { entry, api, onEditSweep, edit }
}

it('opens the exact native Sweep row despite evicted bodies and a later snapshot', () => {
  const { entry, edit, api, onEditSweep } = fixture()
  expect(edit).toBeDefined(); expect(edit.disabled).toBe(false)
  edit.click()
  expect(onEditSweep).toHaveBeenCalledWith(entry, 0)
  expect(onEditSweep.mock.calls[0][0]).toBe(entry)
  expect(api.editFeature).not.toHaveBeenCalled()
})

it.each([{ cursor: -2 }, { cursor: 0 }, { subCursor: 0 }])('requires the current complete history position (%j)', options => {
  const { edit, onEditSweep } = fixture(options)
  expect(edit).toBeDefined(); expect(edit.disabled).toBe(true)
  edit.click(); expect(onEditSweep).not.toHaveBeenCalled()
})

it.each([true, false])('does not offer obsolete editing while rollout is disabled (evicted=%s)', evicted => {
  expect(fixture({ enabled: false, evicted }).edit).toBeUndefined()
})

it('does not promote an unknown Sweep proof contract to recovery-independent editing', () => {
  expect(fixture({ version: 2 }).edit).toBeUndefined()
})
