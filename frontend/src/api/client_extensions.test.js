import { afterEach, expect, it, vi } from 'vitest'
import * as client from './client.js'
import * as editor from '../cadnano-editor/api.js'
import { store } from '../state/store.js'
import { editorStore } from '../cadnano-editor/store.js'
import { nadocBroadcast } from '../shared/broadcast.js'

vi.mock('../shared/broadcast.js', () => ({ nadocBroadcast: { emit: vi.fn() } }))
vi.mock('../shared/connection_monitor.js', () => ({ notifyRequestSuccess: vi.fn(), notifyRequestFailure: vi.fn(), pokeProbe: vi.fn() }))
const response = (payload, status = 200) => ({ ok: status < 400, status, headers: new Headers(), json: async () => payload })
const design = () => ({ id: 'extensions', helices: [], strands: [], extensions: [], feature_log: [], feature_log_cursor: -1 })
const packet = (revision, source = design()) => ({ design: source, revision, validation: {}, nucleotides: [], helix_axes: [] })
async function fixture(host, source = design()) {
  const api = host === '3D' ? client : editor
  api.resetRevisionWatermark()
  const initial = packet(4, source)
  const fetch = vi.fn(async () => response(initial)); vi.stubGlobal('fetch', fetch)
  if (host === '3D') {
    store.setState({ assemblyActive: false, featureSeekPending: false, currentDesign: null, lastError: null })
    await client._syncFromDesignResponse(initial)
  } else await editor.fetchDesign()
  fetch.mockClear(); nadocBroadcast.emit.mockClear()
  return { api, fetch, current: () => host === '3D' ? store.getState().currentDesign : editorStore.getState().design }
}
afterEach(() => {
  window.dispatchEvent(new Event('nadoc:document-reset'))
  localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals()
})

it.each(['3D', '2D'])('%s ordinary extension calls send exact revision and adopt once without follow-up GET', async host => {
  const f = await fixture(host); let revision = 4
  f.fetch.mockImplementation(async () => response(packet(++revision)))
  await f.api.upsertStrandExtensionsBatch([{ strandId: 's', end: 'five_prime', sequence: 'AT' }])
  await f.api.deleteStrandExtensionsBatch(['e'])
  expect(f.fetch.mock.calls.map(([path, options]) => [path, options.method, JSON.parse(options.body).expected_revision])).toEqual([
    ['/api/design/extensions/batch', 'POST', 4], ['/api/design/extensions/batch', 'DELETE', 5],
  ])
  expect(f.fetch.mock.calls[0][1].headers['X-NADOC-Skip-Geometry']).toBe(host === '2D' ? '1' : undefined)
  expect(f.current().id).toBe('extensions'); expect(nadocBroadcast.emit).toHaveBeenCalledTimes(2)
})
it.each(['3D', '2D'])('%s refusal keeps source and does not activate/retry a protected loadout', async host => {
  const f = await fixture(host), source = f.current()
  f.fetch.mockResolvedValue(response({ detail: { code: 'protected_simulation_loadout', message: 'Read-only source' } }, 409))
  expect(await f.api.upsertStrandExtensionsBatch([{ strandId: 's', end: 'three_prime', sequence: 'A' }])).toBeNull()
  expect(f.current()).toBe(source); expect(f.fetch).toHaveBeenCalledTimes(1)
  expect(nadocBroadcast.emit).not.toHaveBeenCalled()
})
it.each(['3D', '2D'])('%s same-ID reset retires a held extension response', async host => {
  const f = await fixture(host), source = f.current(); let finish
  f.fetch.mockReturnValue(new Promise(resolve => { finish = resolve }))
  const pending = f.api.deleteStrandExtensionsBatch(['e'])
  window.dispatchEvent(new Event('nadoc:document-reset'))
  finish(response(packet(5)))
  expect(await pending).toBeNull(); expect(f.current()).toBe(source)
  expect(nadocBroadcast.emit).not.toHaveBeenCalled()
})
it('3D synthetic-only deletion preserves unrelated nucleotide and axis caches without a GET', async () => {
  const f = await fixture('3D')
  const real = { helix_id: 'h', position: [1, 2, 3] }, axes = { h: { start: [0, 0, 0], end: [0, 0, 1] } }
  store.setState({ currentGeometry: [real, { helix_id: '__ext_e' }], currentHelixAxes: axes })
  f.fetch.mockResolvedValue(response({ design: design(), revision: 5, validation: {}, nucleotides: [],
    partial_geometry: true, changed_helix_ids: ['__ext_e'] }))
  expect(await client.deleteStrandExtension('e')).not.toBeNull()
  expect(store.getState().currentGeometry).toEqual([real]); expect(store.getState().currentHelixAxes).toBe(axes)
  expect(f.fetch).toHaveBeenCalledTimes(1)
})
it('3D empty delete acknowledgement leaves existing geometry intact', async () => {
  const f = await fixture('3D'), geometry = [{ helix_id: 'h', position: [1, 2, 3] }]
  store.setState({ currentGeometry: geometry })
  f.fetch.mockResolvedValue(response({ design: design(), revision: 4, no_op: true, validation: {}, nucleotides: [],
    partial_geometry: true, changed_helix_ids: [] }))
  expect(await client.deleteStrandExtensionsBatch([])).not.toBeNull()
  expect(store.getState().currentGeometry).toBe(geometry); expect(f.fetch).toHaveBeenCalledTimes(1)
})
it.each(['3D', '2D'])('%s acknowledges unchanged organized PUT and batch only with an explicit no-op receipt', async host => {
  const source = design(), extension = { id: 'e', strand_id: 's', end: 'five_prime', sequence: 'AT', modification: null, label: null }
  source.extensions = [extension]; source.strands = [{ id: 's', domains: [] }]
  source.group_organization = { version: 1, groups: [] }
  const f = await fixture(host, source)
  f.fetch.mockImplementation(async () => response({ ...packet(4, structuredClone(source)), no_op: true }))
  const updated = await f.api.updateStrandExtension('e', { sequence: 'AT' })
  expect(updated?.no_op).toBe(true); expect(f.current()).toBe(updated.design)
  const batch = await f.api.upsertStrandExtensionsBatch([{ strandId: 's', end: 'five_prime', sequence: 'AT' }])
  expect(batch?.no_op).toBe(true); expect(f.current()).toBe(batch.design)
  expect(batch.design.extensions).toEqual([extension]); expect(batch.design.feature_log).toEqual([])
  expect(f.fetch).toHaveBeenCalledTimes(2)
  expect(f.fetch.mock.calls.every(([, opts]) => JSON.parse(opts.body).expected_revision === 4)).toBe(true)
})
it.each([
  ['missing acknowledgement', 4, undefined], ['contradictory acknowledgement', 5, true],
  ['malformed acknowledgement', 4, 'true'], ['older acknowledged reply', 3, true],
])('3D rejects %s without adopting or persisting its packet', async (_label, revision, no_op) => {
  const f = await fixture('3D'), source = f.current(), geometry = store.getState().currentGeometry
  f.fetch.mockResolvedValue(response({ ...packet(revision), ...(no_op === undefined ? {} : { no_op }) }))
  expect(await f.api.updateStrandExtension('e', { sequence: 'AT' })).toBeNull()
  expect(f.current()).toBe(source); expect(store.getState().currentGeometry).toBe(geometry)
  expect(nadocBroadcast.emit).not.toHaveBeenCalled(); expect(f.fetch).toHaveBeenCalledTimes(1)
})
it.each(['helices', 'strands', 'extensions', 'feature_log'])('2D refuses malformed topology-only %s before canonical adoption', async key => {
  const f = await fixture('2D'), source = f.current(), malformed = design()
  malformed[key] = null
  f.fetch.mockResolvedValue(response({ design: malformed, revision: 5, validation: {} }))
  expect(await f.api.updateStrandExtension('e', { sequence: 'AT' })).toBeNull()
  expect(f.current()).toBe(source); expect(nadocBroadcast.emit).not.toHaveBeenCalled()
})
