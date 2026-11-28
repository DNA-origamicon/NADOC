import { afterEach, expect, it, vi } from 'vitest'
import { instanceFeatureFields, editInstanceHistoryFeature } from './instance_feature_editor.js'
import { historyDialogHost } from './primitives/history_dialog_host.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { recordAssemblyResponse } from '../api/assembly_response_authority.js'

afterEach(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); document.body.innerHTML = '' })
it('offers only recorded native inputs and preserves omitted patch fields', () => {
  expect(instanceFeatureFields({ feature_type: 'snapshot', op_kind: 'overhang-sequence',
    params: { _proof_version: 1, label: 'Named' } }).map(f => f.key)).toEqual(['label'])
  expect(instanceFeatureFields({ feature_type: 'snapshot', op_kind: 'overhang-extrude',
    params: { _proof_version: 1, length_bp: 8 } }).map(f => f.key)).toEqual(['length_bp'])
  expect(instanceFeatureFields({ feature_type: 'snapshot', op_kind: 'overhang-extrude', params: { length_bp: 8 } })).toEqual([])
})
function fixture() {
  const source = { id: 'part', feature_log_cursor: -1, feature_log: [{ id: 'extrude', feature_type: 'snapshot',
    op_kind: 'overhang-extrude', params: { _proof_version: 1, length_bp: 8 } }] }
  const assemblySource = { id: 'assembly', instances: [{ id: 'instance', source: { type: 'inline', design: source } }] }
  recordAssemblyResponse(assemblySource, { revision: 4 })
  const store = createMockStore({ assemblyActive: true, currentAssembly: assemblySource })
  const transport = { start: vi.fn() }
  return { source, assemblySource, store, instanceId: 'instance', rowIndex: 0,
    api: { assemblyHistoryAPI: transport }, getDocumentId: () => 'doc' }
}
it('invalidates selected history when its parent or selected target changes', () => {
  const f = fixture()
  let selected = true
  const host = historyDialogHost({ ...f, isTargetCurrent: () => selected })
  expect(host.context).toMatchObject({ instanceId: 'instance', designId: 'part', revision: 4, featureIds: ['extrude'] })
  expect(host.current()).toBe(true)
  selected = false
  expect(host.current()).toBe(false)
  selected = true
  f.store.setState({ currentAssembly: { ...f.assemblySource } })
  expect(host.current()).toBe(false)
})
it('discards an open editor after the parent assembly changes', async () => {
  const f = fixture(), promise = editInstanceHistoryFeature(f)
  expect(document.querySelector('input').value).toBe('8')
  f.store.setState({ currentAssembly: { ...f.assemblySource } })
  const button = name => [...document.querySelectorAll('button')].find(b => b.textContent === name)
  button('Save').click()
  expect(document.querySelector('[role="alert"]').textContent).toContain('changed')
  button('Cancel').click(); await promise
  expect(f.api.assemblyHistoryAPI.start).not.toHaveBeenCalled()
})
