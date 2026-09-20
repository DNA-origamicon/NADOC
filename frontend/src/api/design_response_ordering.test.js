import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { store } from '../state/store.js'
import {
  _syncFromDesignResponse, _syncDesignAuthoringResponse,
  resetRevisionWatermark, saveAnnotations, saveViewVolumes,
} from './client.js'

const design = { id: 'part', helices: [], strands: [], annotations: [], view_volumes: [] }
const response = json => ({ ok: true, status: 200, headers: { get: () => null }, json: async () => json })

beforeEach(() => {
  resetRevisionWatermark()
  store.setState({ currentDesign: { ...design }, assemblyActive: false })
  vi.stubGlobal('fetch', vi.fn())
})
afterEach(() => vi.unstubAllGlobals())

it('applies geometry arriving after an annotation acknowledgement without erasing annotations', async () => {
  fetch.mockResolvedValueOnce(response({ revision: 11, annotations: [{ id: 'note' }], annotations_enabled: false }))
  await saveAnnotations({ annotations: [{ id: 'note' }], enabled: false })
  await _syncFromDesignResponse({ revision: 10, design: { ...design, name: 'edited' },
    nucleotides: [], helix_axes: [] })
  expect(store.getState().currentDesign).toMatchObject({
    name: 'edited', annotations: [{ id: 'note' }], annotations_enabled: false,
  })
  expect(store.getState().currentGeometry).toEqual([])
})

it('preserves camera metadata while accepting a required topology response', async () => {
  _syncDesignAuthoringResponse({ revision: 12, design: { ...design, camera_poses: [{ id: 'pose' }] } }, 'camera_poses')
  await _syncFromDesignResponse({ revision: 11, design: { ...design, name: 'new topology', camera_poses: [] },
    nucleotides: [], helix_axes: [] })
  expect(store.getState().currentDesign).toMatchObject({ name: 'new topology', camera_poses: [{ id: 'pose' }] })
})

it('ignores a partial acknowledgement when its design was closed during the request', async () => {
  let resolve
  fetch.mockImplementationOnce(() => new Promise(r => { resolve = r }))
  const saving = saveViewVolumes([{ id: 'volume' }])
  await vi.waitFor(() => expect(resolve).toBeTypeOf('function'))
  store.setState({ currentDesign: { ...design, id: 'other' } })
  resolve(response({ revision: 40, view_volumes: [{ id: 'volume' }] }))
  expect(await saving).toBeNull()
  await _syncFromDesignResponse({ revision: 39, design: { ...design, id: 'other' },
    nucleotides: [], helix_axes: [] })
  expect(store.getState().currentDesign.view_volumes).toEqual([])
})
