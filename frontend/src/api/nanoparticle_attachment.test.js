import { afterEach, expect, it, vi } from 'vitest'
import { attachNanoparticleToOverhang } from './client.js'
import { store } from '../state/store.js'

afterEach(() => {
  vi.unstubAllGlobals()
  store.setState({ currentDesign: null, lastError: null })
})

it('propagates an attachment rejection instead of reporting a successful selection', async () => {
  store.setState({ currentDesign: { id: 'attachment-test' } })
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: false, status: 422, headers: new Headers(),
    json: async () => ({ detail: 'This overhang is already occupied.' }),
  })))
  await expect(attachNanoparticleToOverhang('particle', 'target')).rejects.toThrow('already occupied')
  const body = JSON.parse(fetch.mock.calls[0][1].body)
  expect(body.expected_design_id).toBe('attachment-test')
  expect(body.overhang_id).toBe('target')
})
