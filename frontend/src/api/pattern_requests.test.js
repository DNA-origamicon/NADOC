import { afterEach, expect, it, vi } from 'vitest'
import { createCircularPattern, createLinearPattern, _syncFromDesignResponse, resetRevisionWatermark } from './client.js'
import { store } from '../state/store.js'

afterEach(() => {
  window.dispatchEvent(new Event('nadoc:document-reset'))
  resetRevisionWatermark(); localStorage.clear(); vi.unstubAllGlobals()
})

it.each([createCircularPattern, createLinearPattern])('rejects failed pattern requests so tools keep their preview open', async createPattern => {
  const design = { id: 'source', helices: [], strands: [] }
  store.setState({ currentDesign: design, assemblyActive: false })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false, status: 400, headers: { get: () => null },
    json: async () => ({ detail: 'Source cluster no longer exists' }),
  }))
  await expect(createPattern({})).rejects.toThrow('Source cluster no longer exists')
  expect(store.getState().currentDesign).toBe(design)
})

it.each([
  ['linear-pattern', createLinearPattern], ['circular-pattern', createCircularPattern],
])('adopts the complete %s response with one POST and no later geometry request', async (kind, createPattern) => {
  resetRevisionWatermark()
  const source = { id: 'pattern-part', helices: [], strands: [], feature_log: [] }
  store.setState({ currentDesign: source, assemblyActive: false, featureSeekPending: false, lastError: null })
  await _syncFromDesignResponse({ design: source, revision: 7, nucleotides: [], helix_axes: [] })
  const nucleotide = { helix_id: 'copy', bp_index: 0, direction: 'FORWARD',
    backbone_position: [8, 2, 3], base_position: [8, 3, 3], base_normal: [0, 1, 0],
    axis_tangent: [0, 0, 1], slab_position: [8, 2, 3], slab_quaternion: [0, 0, 0, 1],
    placement_source: 'native-full-o5-v1' }
  const result = { design: { ...source, name: 'Patterned' }, revision: 8, nucleotides: [nucleotide],
    helix_axes: [{ helix_id: 'copy', start: [8, 2, 3], end: [8, 2, 4] }],
    straight_positions_by_helix: { copy: { FORWARD: { bp: [0], bb: [[1, 2, 3]], bs: [[1, 3, 3]],
      bn: [[0, 1, 0]], at: [[0, 0, 1]], sp: [[1, 2, 3]], sq: [[0, 0, 0, 1]], pv: ['native-full-o5-v1'] } } },
    straight_helix_axes: [{ helix_id: 'copy', start: [1, 2, 3], end: [1, 2, 4] }],
  }
  const fetch = vi.fn(async () => ({ ok: true, status: 200, headers: new Headers(), json: async () => result }))
  vi.stubGlobal('fetch', fetch)
  expect(await createPattern({})).toBe(result)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0][0]).toBe(`/api/design/${kind}`)
  expect(fetch.mock.calls[0][1].method).toBe('POST')
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ expected_design_id: source.id, expected_revision: 7 })
  expect(store.getState().currentDesign).toBe(result.design)
  expect(store.getState().currentGeometry).toBe(result.nucleotides)
  expect(store.getState().currentHelixAxes.copy.start).toEqual([8, 2, 3])
  expect(store.getState().straightGeometry[0].backbone_position).toEqual([1, 2, 3])
  expect(store.getState().straightHelixAxes.copy.start).toEqual([1, 2, 3])
})
