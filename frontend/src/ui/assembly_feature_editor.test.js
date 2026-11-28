import { afterEach, expect, it, vi } from 'vitest'
import { assemblyFeatureFields, editAssemblyHistoryFeature } from './assembly_feature_editor.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { recordAssemblyResponse } from '../api/assembly_response_authority.js'

const flush = async () => { for (let i = 0; i < 18; i++) await Promise.resolve() }
afterEach(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); document.body.innerHTML = '' })
it('reads recorded inputs, excluding legacy summaries and unset patch fields', () => {
  expect(assemblyFeatureFields({ op_kind: 'assembly-patch-joint', params: { command_version: 1,
    inputs: { current_value: 0, min_limit: null, max_limit: 2 } } }).map(f => f.key)).toEqual(['current_value', 'max_limit'])
  expect(assemblyFeatureFields({ op_kind: 'assembly-polymerize', params: { count: 3 } })).toEqual([])
  expect(assemblyFeatureFields({ op_kind: 'assembly-overhang-connection-add', params: {
    command_version: 1, inputs: { length_value: 3, length_unit: 'bp', bridge_sequence: null },
  } }).map(f => f.key)).toContain('bridge_sequence')
  expect(assemblyFeatureFields({ op_kind: 'assembly-instance-overhang-patch', params: {
    command_version: 1, inputs: { label: 'Named', sequence: null, rotation: null }, input_fields_set: ['label'],
  } }).map(f => f.key)).toEqual(['label'])
})
function fixture() {
  const source = { id: 'assembly', feature_log_cursor: -1, feature_log: [
    { id: 'gear', op_kind: 'assembly-patch-gear', params: { command_version: 1, ratio: 99, inputs: { ratio: 3 } } },
    { id: 'resolve', op_kind: 'assembly-resolve-gear' }] }
  recordAssemblyResponse(source, { revision: 4 })
  const store = createMockStore({ assemblyActive: true, currentAssembly: source })
  const transport = { start: vi.fn(async () => ({ job_id: 'job' })),
    poll: vi.fn(async () => ({ status: 'complete', result: { status: 'ready' } })),
    commit: vi.fn(async () => ({})), refreshCommitted: vi.fn(async () => ({})), apply: vi.fn(), cancel: vi.fn(async () => ({})) }
  const promise = editAssemblyHistoryFeature({ source, store, rowIndex: 0, api: { assemblyHistoryAPI: transport }, getDocumentId: () => 'doc' })
  return { source, store, transport, promise }
}
const button = name => [...document.querySelectorAll('button')].find(b => b.textContent === name)
it('edits an earlier row and applies only after downstream regeneration succeeds', async () => {
  const f = fixture()
  const input = document.querySelector('input')
  expect(input.value).toBe('3')
  input.value = '4'; button('Save').click()
  const modal = await f.promise
  expect(f.transport.start).not.toHaveBeenCalled()
  button('Apply edit').click(); await flush()
  expect(f.transport.start).toHaveBeenCalledWith({ operation: 'edit', index: 0, inputs: { ratio: 4 }, expected_revision: 4 }, expect.anything())
  expect(f.transport.apply).toHaveBeenCalledOnce()
  expect(modal.isOpen()).toBe(false)
})
it('discards inputs when the source changes before saving', async () => {
  const f = fixture()
  f.store.setState({ currentAssembly: { ...f.source } })
  button('Save').click(); await flush()
  expect(document.querySelector('[role="alert"]').textContent).toContain('changed')
  button('Cancel').click(); await f.promise
  expect(f.transport.start).not.toHaveBeenCalled()
})
it('reports downstream refusal and leaves the assembly unchanged', async () => {
  const f = fixture()
  f.transport.poll.mockResolvedValue({ status: 'complete', result: { status: 'failed', issues: [{ detail: 'Joint no longer exists' }] } })
  button('Save').click(); const modal = await f.promise
  button('Apply edit').click(); await flush()
  expect(document.querySelector('[role="status"]').textContent).toBe('Joint no longer exists')
  expect(f.transport.commit).not.toHaveBeenCalled()
  expect(button('Apply edit').disabled).toBe(false)
  modal.close()
})
