import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { autoScaffoldSeamless } from './client.js'
import { store } from '../state/store.js'
import { showToast } from '../ui/toast.js'

vi.mock('../ui/toast.js', () => ({ showToast: vi.fn() }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('fetch', vi.fn())
})
afterEach(() => {
  vi.unstubAllGlobals()
  store.setState({ currentDesign: null })
})

it('applies the available route and displays closure warnings', async () => {
  const warning = '[Seamless] No closed route with one buried nick was achieved.'
  fetch.mockResolvedValueOnce({
    ok: true, status: 200, headers: { get: () => null },
    json: async () => ({
      design: { id: 'open-route', feature_log: [], strands: [], helices: [] },
      nucleotides: [], warnings: [warning],
    }),
  })
  expect(await autoScaffoldSeamless()).toBeTruthy()
  expect(store.getState().currentDesign.id).toBe('open-route')
  expect(showToast).toHaveBeenCalledWith(warning, { severity: 'warning', duration: 10000 })
})

it('does not warn for an informational reset after a successful reroute', async () => {
  fetch.mockResolvedValueOnce({
    ok: true, status: 200, headers: { get: () => null },
    json: async () => ({ design: { feature_log: [], strands: [], helices: [] }, nucleotides: [], warnings: ['Reset prior auto-scaffold route to the structural seed.'] }),
  })
  expect(await autoScaffoldSeamless()).toBeTruthy()
  expect(showToast).not.toHaveBeenCalled()
})
