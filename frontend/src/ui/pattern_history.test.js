import { afterEach, expect, it, vi } from 'vitest'
import { initFeatureLogPanel } from './feature_log_panel.js'

afterEach(() => { window.dispatchEvent(new Event('nadoc:document-reset')); document.body.innerHTML = ''; vi.unstubAllGlobals() })

function fixture(organized = true) {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', () => 1)
  document.body.innerHTML = '<div id="left-panel"><div class="tab-content"><h2 id="feature-log-panel-heading"><span>Feature Log</span></h2><span id="feature-log-panel-arrow"></span><div id="feature-log-panel-body"></div></div></div>'
  const entry = { id: 'stable-feature', feature_type: 'snapshot', op_kind: 'linear-pattern', label: 'Linear pattern', evicted: true,
    params: { instances: 3, spacing: 10, direction: 'X', cluster_ids: ['historical-placement'],
      _organization_copy: { version: 1, group_ids: ['historical-group'] } } }
  const state = { currentDesign: { id: 'part', feature_log_cursor: -1, feature_log: [entry],
    ...(organized ? { group_organization: { version: 1, groups: [{ id: 'current-group' }] } } : {}),
    loadouts: [{ id: 'main', name: 'Main' }], active_loadout_id: 'main', cluster_transforms: [], deformations: [], overhangs: [] },
  currentAssembly: null, assemblyActive: false }
  const context = { designId: 'part', revision: 10 }
  const api = { capturePatternContext: vi.fn(() => context), isPatternContextCurrent: vi.fn(() => true),
    editPatternFeatureInputs: vi.fn(async () => null), editFeature: vi.fn() }
  initFeatureLogPanel({ getState: () => state, subscribeSlice: () => () => {} }, { api })
  return { api, context }
}

it('edits an evicted native pattern using original feature identity and keeps a refused historical draft', async () => {
  const { api, context } = fixture()
  const edit = [...document.querySelectorAll('#fl-list [data-fl-row="1"] button')].find(node => node.textContent === '✎')
  expect(edit).toBeDefined(); expect(edit.disabled).toBe(false)
  edit.click()
  const saved = document.querySelector('[aria-label="Saved pattern copy selection"]')
  expect(saved).not.toBeNull()
  expect(saved.textContent).toContain('historical-placement')
  expect(saved.textContent).toContain('historical-group')
  expect(saved.textContent).not.toContain('current-group')
  expect(saved.querySelector('input, select, button')).toBeNull()
  const spacing = document.querySelector('[aria-label="Spacing 1 (nm)"]')
  spacing.value = '19'; spacing.dispatchEvent(new Event('input'))
  const save = [...document.querySelectorAll('button')].find(node => node.textContent === 'Save')
  save.click(); await Promise.resolve(); await Promise.resolve()
  expect(api.editPatternFeatureInputs).toHaveBeenCalledWith(0, expect.objectContaining({ spacing: 19,
    cluster_ids: ['historical-placement'], _organization_copy: { version: 1, group_ids: ['historical-group'] } }), context, 'stable-feature')
  expect(api.editFeature).not.toHaveBeenCalled()
  expect(document.querySelector('[aria-label="Edit Linear Pattern"]')).not.toBeNull()
  api.isPatternContextCurrent.mockReturnValue(false)
  save.click(); await Promise.resolve()
  expect(api.editPatternFeatureInputs).toHaveBeenCalledTimes(1)
  expect(document.querySelector('.cp-readout').textContent).toMatch(/part changed/i)
})

it('keeps the legacy evicted-pattern restriction', () => {
  fixture(false)
  expect([...document.querySelectorAll('#fl-list [data-fl-row="1"] button')].find(node => node.textContent === '✎')).toBeUndefined()
})
