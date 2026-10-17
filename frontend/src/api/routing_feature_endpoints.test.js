import { afterEach, expect, it, vi } from 'vitest'
import { store } from '../state/store.js'
import { captureRoutingEditContext, getRoutingFeatureInputs, editRoutingFeatureInputs, _syncFromDesignResponse, resetRevisionWatermark } from './client.js'

const child = { feature_type: 'minor', id: 'child', op_subtype: 'nick', params: { _proof_version: 1, helix_id: 'h', bp_index: 5, direction: 'FORWARD' } }
const parent = { id: 'parent', feature_type: 'routing-cluster', children: [child] }
const source = () => ({ id: 'part', feature_log: [structuredClone(parent)], helices: [], strands: [], crossovers: [], forced_ligations: [], cluster_transforms: [] })
const prefix = () => ({ kind: 'nick', params: structuredClone(child.params), prefix: { helices: [], strands: [], crossovers: [], forced_ligations: [] }, source_design_id: 'part', source_revision: 7, feature_id: 'parent', child_id: 'child' })
async function setup() {
  resetRevisionWatermark(); store.setState({ assemblyActive: false, currentAssembly: null, featureSeekPending: false, lastError: null })
  await _syncFromDesignResponse({ design: source(), nucleotides: [], helix_axes: [], validation: {}, revision: 7 })
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
  return { fetch, context: captureRoutingEditContext() }
}
const response = body => ({ ok: true, status: 200, headers: new Headers({ 'Content-Type': 'application/json' }), json: async () => body })
afterEach(() => { window.dispatchEvent(new Event('nadoc:document-reset')); vi.unstubAllGlobals() })

it('loads exact pre-child choices without adopting prefix topology or requesting geometry', async () => {
  const { fetch, context } = await setup(), packet = prefix(); fetch.mockResolvedValue(response(packet))
  expect(await getRoutingFeatureInputs(0, 0, context, 'parent', 'child')).toBe(packet)
  const [url, options] = fetch.mock.calls[0], parsed = new URL(url, 'http://localhost')
  expect(parsed.pathname).toBe('/api/design/features/0/routing-inputs')
  expect(Object.fromEntries(parsed.searchParams)).toEqual({ sub_index: '0', expected_design_id: 'part', expected_revision: '7', expected_feature_id: 'parent', expected_child_id: 'child' })
  expect(options.method).toBe('GET'); expect(store.getState().currentDesign).toBe(context.source)
  expect(fetch).toHaveBeenCalledOnce()
})

it('publishes a guarded child edit and adopts the same candidate geometry in one response', async () => {
  const { fetch, context } = await setup()
  const nucleotide = { helix_id: 'h', bp_index: 0, direction: 'FORWARD', backbone_position: [8, 2, 3], base_position: [8, 3, 3],
    base_normal: [0, 1, 0], axis_tangent: [0, 0, 1], slab_position: [8, 2, 3], slab_quaternion: [0, 0, 0, 1], placement_source: 'native-full-o5-v1' }
  const result = { design: source(), nucleotides: [nucleotide], helix_axes: [{ helix_id: 'h', start: [8, 2, 3], end: [8, 2, 4] }], validation: {}, revision: 8 }
  fetch.mockResolvedValue(response(result))
  expect(await editRoutingFeatureInputs(0, 0, { ...child.params, bp_index: 7 }, context, 'parent', 'child')).toBe(result)
  expect(fetch.mock.calls[0][0]).toBe('/api/design/features/0/edit?sub_index=0')
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ params: { ...child.params, bp_index: 7 }, expected_design_id: 'part', expected_revision: 7, expected_feature_id: 'parent', expected_child_id: 'child' })
  expect(store.getState().currentDesign).toBe(result.design); expect(store.getState().currentGeometry).toBe(result.nucleotides)
  expect(store.getState().currentHelixAxes.h.start).toEqual([8, 2, 3]); expect(fetch).toHaveBeenCalledOnce()
})

it.each(['feature_id', 'child_id', 'source_design_id', 'source_revision', 'kind'])('rejects a prefix response with mismatched %s', async key => {
  const { fetch, context } = await setup(); fetch.mockResolvedValue(response({ ...prefix(), [key]: key === 'source_revision' ? 8 : 'wrong' }))
  await expect(getRoutingFeatureInputs(0, 0, context, 'parent', 'child')).rejects.toThrow(/changed|invalid|match/i)
  expect(store.getState().currentDesign).toBe(context.source)
})

it('refuses a changed child before a request', async () => {
  const { fetch, context } = await setup()
  await expect(editRoutingFeatureInputs(0, 0, child.params, context, 'parent', 'other')).rejects.toThrow(/changed/i)
  expect(fetch).not.toHaveBeenCalled()
})

it.each(['prefix', 'edit'])('drops a held %s response after a same-ID reset', async kind => {
  const { fetch, context } = await setup(); let finish
  fetch.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const request = kind === 'prefix' ? getRoutingFeatureInputs(0, 0, context, 'parent', 'child') : editRoutingFeatureInputs(0, 0, child.params, context, 'parent', 'child')
  const rejected = expect(request).rejects.toThrow(/changed|accepted|reopen/i)
  window.dispatchEvent(new Event('nadoc:document-reset')); const newer = source(); store.setState({ currentDesign: newer })
  finish(response(kind === 'prefix' ? prefix() : { design: source(), nucleotides: [], validation: {}, revision: 8 }))
  await rejected; expect(store.getState().currentDesign).toBe(newer)
})

it.each([{ design: source(), revision: 8 }, { design: source(), nucleotides: [], revision: 7 }, { design: source(), nucleotides: [], revision: 8, partial_geometry: true }])('refuses incomplete or stale edit receipts without a geometry fallback', async result => {
  const { fetch, context } = await setup(); fetch.mockResolvedValue(response(result))
  await expect(editRoutingFeatureInputs(0, 0, child.params, context, 'parent', 'child')).rejects.toThrow()
  expect(store.getState().currentDesign).toBe(context.source); expect(fetch).toHaveBeenCalledOnce()
})
