import { afterEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../../test-helpers/mock_store.js'
import { showFeatureReorder, showFeatureSuppression } from './feature_reorder_dialog.js'

const flush = async () => { for (let i = 0; i < 12; ++i) await Promise.resolve() }
afterEach(() => { document.body.innerHTML = '' })
function setup(overrides = {}) {
  const source = { id: 'part', feature_log: [{ id: 'a', label: 'First' }, { id: 'b', label: 'Second' }] }
  const store = createMockStore({ currentDesign: source })
  const transport = { start: vi.fn(async () => ({ job_id: 'job' })),
    poll: vi.fn(async () => ({ status: 'complete', result: { status: 'ready' } })),
    commit: vi.fn(async () => ({ job_id: 'job', status: 'committed' })),
    refreshCommitted: vi.fn(async () => ({ design: { id: 'part' } })),
    apply: vi.fn(), cancel: vi.fn(async () => ({})), ...overrides }
  const modal = showFeatureReorder({ source, store, api: { partRepairAPI: transport,
    currentRevisionWatermark: () => 4 }, rowIndex: 0, getDocumentId: () => 'doc' })
  const move = [...document.querySelectorAll('button')].find(button => button.textContent === 'Move')
  const select = document.querySelector('select')
  const start = () => { select.value = '1'; select.dispatchEvent(new Event('change')); move.click() }
  return { source, store, transport, modal, move, start }
}
it('moves a captured row only after successful regeneration and checked refresh', async () => {
  const { move, start, modal, transport } = setup()
  expect(move.disabled).toBe(true)
  start(); await flush()
  expect(transport.start).toHaveBeenCalledWith({ operation: 'reorder', index: 0, destination: 1,
    expected_revision: 4 }, { context: { docId: 'doc', designId: 'part', loadoutId: null, revision: 4 } })
  expect(transport.commit).toHaveBeenCalledOnce()
  expect(transport.apply).toHaveBeenCalledOnce()
  expect(modal.isOpen()).toBe(false)
})
it('shows a dependency refusal without publishing', async () => {
  const { start, transport, modal } = setup({ poll: vi.fn(async () => ({ status: 'complete', result: {
    status: 'failed', issues: [{ detail: { detail: 'Cannot cross the source Extrude.' } }] } })) })
  start(); await flush()
  expect(document.querySelector('[role="status"]').textContent).toContain('Cannot cross the source Extrude')
  expect(transport.commit).not.toHaveBeenCalled()
  expect(transport.cancel).toHaveBeenCalled()
  modal.close()
})
it('cancels a late start when the user closes before its response', async () => {
  let finish
  const { start, modal, transport } = setup({ start: vi.fn(() => new Promise(resolve => { finish = resolve })) })
  start(); modal.close(); finish({ job_id: 'late' }); await flush()
  expect(transport.cancel).toHaveBeenCalledWith('late', expect.anything())
  expect(transport.commit).not.toHaveBeenCalled()
})
it('retires on same-ID source replacement during evaluation', async () => {
  let finish
  const { start, modal, store, source, transport } = setup({ poll: vi.fn(() => new Promise(resolve => { finish = resolve })) })
  start(); await flush(); store.setState({ currentDesign: { ...source } })
  finish({ status: 'complete', result: { status: 'ready' } }); await flush()
  expect(modal.isOpen()).toBe(false)
  expect(transport.commit).not.toHaveBeenCalled()
})
it('keeps the dialog open while publication is pending', async () => {
  let finish
  const { start, modal, transport } = setup({ commit: vi.fn(() => new Promise(resolve => { finish = resolve })) })
  start(); await flush(); modal.close()
  expect(modal.isOpen()).toBe(true)
  expect(transport.cancel).not.toHaveBeenCalled()
  finish({ job_id: 'job', status: 'committed' }); await flush()
  expect(transport.apply).toHaveBeenCalledOnce()
  expect(modal.isOpen()).toBe(false)
})

it.each([false, true])('publishes suppression state %s with the existing transaction', async suppressed => {
  const source = { id: 'part', feature_log: [{ id: 'a', suppressed }] }
  const store = createMockStore({ currentDesign: source })
  const transport = { start: vi.fn(async () => ({ job_id: 'job' })),
    poll: vi.fn(async () => ({ status: 'complete', result: { status: 'ready' } })),
    commit: vi.fn(async () => ({ revision: 5 })), refreshCommitted: vi.fn(async () => ({})),
    apply: vi.fn(), cancel: vi.fn(async () => ({})) }
  showFeatureSuppression({ source, store, rowIndex: 0, getDocumentId: () => 'doc',
    api: { partRepairAPI: transport, currentRevisionWatermark: () => 4 } })
  expect(document.querySelector('select')).toBeNull()
  const action = [...document.querySelectorAll('button')].find(b => b.textContent === (suppressed ? 'Unsuppress' : 'Suppress'))
  expect(action.disabled).toBe(false)
  action.click(); await flush()
  expect(transport.start).toHaveBeenCalledWith({ operation: 'suppress', index: 0,
    suppressed: !suppressed, expected_revision: 4 }, expect.anything())
  expect(transport.apply).toHaveBeenCalledOnce()
})
