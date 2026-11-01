import { afterEach, expect, it, vi } from 'vitest'
import { connectionFeatureFields, createConnectionEditAction } from './connection_feature_editor.js'
import { createMockStore } from '../test-helpers/mock_store.js'

const entry = () => ({ id: 'connect', feature_type: 'snapshot', op_kind: 'overhang-bulk', evicted: true,
  params: { _proof_version: 1, connection_composition_version: 4, action: 'connection-version-connect-linker',
    version_id: 'version', connection_id: 'bridge', name: 'First', connection_type: 'root-to-root-ssdna-linker',
    overhang_a_seq: 'AAAA', overhang_b_seq: 'TTTT', bridge_length: 7, bridge_seq: 'NNN' } })
const button = text => [...document.querySelectorAll('button')].find(node => node.textContent === text)
const tick = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }
function setup() {
  const feature = entry(), source = { id: 'part', feature_log: [feature] }
  const store = createMockStore({ currentDesign: source })
  const context = { source, revision: 7 }
  const api = { captureFeatureEditContext: () => context, isFeatureEditContextCurrent: vi.fn(() => true),
    editFeatureInputs: vi.fn(async () => ({ design: source })) }
  return { feature, api, context, open: () => createConnectionEditAction({ api, store })(feature, 0) }
}
afterEach(() => { window.dispatchEvent(new Event('nadoc:document-reset')); document.body.innerHTML = '' })

it('exposes complete connection choices without output identities and accepts evicted recovery', () => {
  expect(connectionFeatureFields(entry()).map(field => field.key)).toEqual([
    'name', 'connection_type', 'overhang_a_seq', 'overhang_b_seq', 'bridge_length', 'bridge_seq'])
  for (const changed of [{ _proof_version: 2 }, { connection_composition_version: 99 }, { _generated_scope: {} }]) {
    expect(connectionFeatureFields({ ...entry(), params: { ...entry().params, ...changed } })).toEqual([])
  }
})
it('cancels the local draft without issuing a canonical request', async () => {
  const d = setup(), pending = d.open()
  document.getElementById('_edit-connection-bridge_length').value = '11'
  button('Cancel').click()
  expect(await pending).toBeNull()
  expect(d.api.editFeatureInputs).not.toHaveBeenCalled()
  expect(d.feature.params.bridge_length).toBe(7)
})
it('sends one source-bound edit and preserves output identities', async () => {
  const d = setup(), pending = d.open()
  document.getElementById('_edit-connection-bridge_length').value = '11'
  button('Save').click(); button('Save').click()
  expect(await pending).toMatchObject({ bridge_length: 11 })
  expect(d.api.editFeatureInputs).toHaveBeenCalledExactlyOnceWith(0, expect.objectContaining({ bridge_length: 11 }), d.context, 'connect')
  expect(d.api.editFeatureInputs.mock.calls[0][1]).not.toHaveProperty('connection_id')
  expect(d.feature.params.bridge_length).toBe(7)
})
it('retains a failed draft for correction and refuses a changed source', async () => {
  const d = setup(), pending = d.open()
  d.api.editFeatureInputs.mockRejectedValueOnce(new Error('Downstream bridge has a dependent feature'))
  document.getElementById('_edit-connection-bridge_length').value = '11'
  button('Save').click(); await tick()
  expect(document.querySelector('[role=alert]').textContent).toContain('dependent feature')
  expect(document.getElementById('_edit-connection-bridge_length').value).toBe('11')
  d.api.isFeatureEditContextCurrent.mockReturnValue(false)
  button('Save').click(); await tick()
  expect(d.api.editFeatureInputs).toHaveBeenCalledTimes(1)
  expect(document.querySelector('[role=alert]').textContent).toContain('part changed')
  button('Cancel').click(); expect(await pending).toBeNull()
})
it('rejects fractional bridge lengths before publication', async () => {
  const d = setup(), pending = d.open()
  document.getElementById('_edit-connection-bridge_length').value = '1.5'
  button('Save').click(); await tick()
  expect(d.api.editFeatureInputs).not.toHaveBeenCalled()
  button('Cancel').click(); await pending
})
it('closes on document reset and ignores a late response', async () => {
  const d = setup(); let release
  d.api.editFeatureInputs.mockImplementation(() => new Promise(resolve => { release = resolve }))
  const pending = d.open(); button('Save').click(); await tick()
  expect(button('Cancel').disabled).toBe(true)
  window.dispatchEvent(new Event('nadoc:document-reset'))
  expect(await pending).toBeNull()
  release({}); await tick()
  expect(document.querySelector('[role=dialog]')).toBeNull()
})

it('exposes native nanoparticle names and creation choices without active/output selectors', () => {
  const feature = { feature_type: 'snapshot', op_kind: 'nanoparticle-connection-version-create',
    params: { _proof_version: 1, nanoparticle_connection_version: 1, nanoparticle_pending_context_version: 1,
      name: 'Alternative', direct_variant: 'end-to-root', active_version_id: 'active', active_duplex_id: 'duplex', version_id: 'new' } }
  expect(connectionFeatureFields(feature).map(field => field.key)).toEqual(['name', 'direct_variant'])
  expect(connectionFeatureFields({ ...feature, op_kind: 'nanoparticle-connection-version-patch' }).map(field => field.key)).toEqual(['name'])
  for (const changes of [{ nanoparticle_connection_version: 2 }, { nanoparticle_pending_context_version: 2 },
    { nanoparticle_application_version: 2 }, { _generated_scope: {} }]) {
    expect(connectionFeatureFields({ ...feature, params: { ...feature.params, ...changes } })).toEqual([])
  }
  expect(connectionFeatureFields({ ...feature, op_kind: 'nanoparticle-connection-version-delete' })).toEqual([])
})

it('edits a nanoparticle name through the guarded historical-input route', async () => {
  const d = setup()
  d.feature.op_kind = 'nanoparticle-connection-version-patch'
  d.feature.params = { _proof_version: 1, nanoparticle_connection_version: 1, nanoparticle_application_version: 1,
    name: 'Active', prior_duplex_id: 'duplex', version_id: 'version' }
  const pending = d.open()
  expect(document.querySelector('[role=dialog]').textContent).toContain('Edit Nanoparticle Connection')
  document.getElementById('_edit-connection-name').value = 'Chosen'
  button('Save').click()
  expect(await pending).toEqual({ name: 'Chosen' })
  expect(d.api.editFeatureInputs).toHaveBeenCalledExactlyOnceWith(0, { name: 'Chosen' }, d.context, 'connect')
  expect(d.feature.params.name).toBe('Active')
})
