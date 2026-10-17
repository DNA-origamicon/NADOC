import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { initFeatureLogPanel } from './feature_log_panel.js'

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', () => 1)
  document.body.innerHTML = '<div id="left-panel"><h2 id="feature-log-panel-heading"><span>History</span></h2>'
    + '<span id="feature-log-panel-arrow"></span><div id="feature-log-panel-body"></div></div>'
})
afterEach(() => { document.body.innerHTML = ''; vi.unstubAllGlobals() })

function render(entry, { enabled = true, cursor = -1 } = {}) {
  const currentDesign = { id: 'part', feature_log_cursor: cursor, feature_log_sub_cursor: null,
    feature_log: [entry, { feature_type: 'snapshot', op_kind: 'later', id: 'later', label: 'Later' }],
    loadouts: [], cluster_transforms: [], deformations: [], overhangs: [] }
  const onEditFeature = vi.fn(), api = { editFeature: vi.fn(), seekFeatures: vi.fn() }
  initFeatureLogPanel({ getState: () => ({ currentDesign, assemblyActive: false }), subscribeSlice: () => () => {} },
    { api, onEditFeature, transformHistoryEnabled: enabled })
  const row = document.querySelector('#fl-list [data-fl-row="1"]')
  return { row, edit: [...row.querySelectorAll('button')].find(button => button.textContent === '✎'), onEditFeature, api }
}

const entryFor = kind => kind === 'cluster_op'
  ? { id: 'feature', feature_type: kind, cluster_id: 'historical-owner', proof_version: 1 }
  : { id: 'feature', feature_type: 'snapshot', op_kind: kind, label: 'Move',
    params: { _proof_version: 1 }, snapshot: null }

it.each(['cluster_op', 'nucleotide-transform', 'nucleotide-transform-batch', 'nucleotide-transform-delete', 'placement-poses'])(
  'opens owned %s from an older row without recovery snapshots or current targets', kind => {
    const entry = entryFor(kind), f = render(entry)
    expect(f.edit).toBeTruthy()
    expect(f.edit.disabled).toBe(false)
    f.edit.click()
    expect(f.onEditFeature).toHaveBeenCalledWith(entry, 0)
    expect(f.api.editFeature).not.toHaveBeenCalled()
    expect(f.api.seekFeatures).not.toHaveBeenCalled()
    expect(f.row.textContent).not.toContain('⚠')
  })

it('requires the latest history cursor for the owned editor', () => {
  expect(render(entryFor('placement-poses'), { cursor: 0 }).edit.disabled).toBe(true)
})

it('keeps new role entry points gated with the corresponding editor', () => {
  expect(render(entryFor('placement-poses'), { enabled: false }).edit).toBeUndefined()
})

it('labels placement creation without offering a pose editor', () => {
  const f = render({ id: 'birth', feature_type: 'cluster_create', cluster_id: 'c', name: 'Arm' })
  expect(f.row.textContent).toContain('Create placement')
  expect(f.row.textContent).not.toContain('move/rotate')
  expect(f.edit).toBeUndefined()
})
