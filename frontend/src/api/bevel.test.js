import { afterEach, expect, it, vi } from 'vitest'
vi.mock('./client.js', () => ({ _request: vi.fn(), _syncFromDesignResponse: vi.fn(),
  currentRevisionWatermark: () => 3, lastErrorMessage: () => '' }))
vi.mock('../shared/doc_id.js', () => ({ getDocId: () => 'active', docHeadersFor: doc => ({ 'X-NADOC-Doc': doc }) }))
import { previewBevel, loadBevelSource } from './bevel.js'

afterEach(() => vi.unstubAllGlobals())
const source = { docId: 'source-document', expected_design_id: 'part', expected_revision: 3 }
it('cancels the exact preparation in its owning document even through a proxy', async () => {
  const controller = new AbortController(), onEvent = vi.fn()
  vi.stubGlobal('fetch', vi.fn((url, options) => {
    if (url.endsWith('/cancel')) return Promise.resolve({ ok: true })
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason)))
  }))
  const prepared = previewBevel(source, { position_bp: 40 }, { signal: controller.signal, onEvent, prepareOnly: true })
  const failure = expect(prepared).rejects.toHaveProperty('name', 'AbortError')
  controller.abort(); await failure
  const [url] = fetch.mock.calls[0], id = new URL(url, 'http://local').searchParams.get('preparation_id')
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(fetch.mock.calls[1]).toEqual([`/api/design/bevel/preparations/${id}/cancel`, {
    method: 'POST', headers: { 'X-NADOC-Doc': 'source-document' }, keepalive: true,
  }])
  expect(onEvent).not.toHaveBeenCalled()
})
it('delivers a prepared token and detaches cancellation after completion', async () => {
  const controller = new AbortController(), onEvent = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ preview_token: 'prepared' }) })))
  await previewBevel(source, {}, { signal: controller.signal, onEvent, prepareOnly: true })
  controller.abort()
  expect(fetch).toHaveBeenCalledOnce()
  expect(onEvent).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'ready', preview_token: 'prepared' }))
})

it('loads the edit input through the ordinary compact Full geometry codec', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({
    paths: [], component: { component_kind: 'corner-preview-dna', nucleotides_compact: {
      h: { FORWARD: { bp: [3], bb: [[1, 2, 3]], bs: [[4, 5, 6]], bn: [[0, 0, 1]],
        at: [[0, 1, 0]], sp: [[4, 5, 6]], sq: [[0, 0, 0, 1]], pv: ['native-full-o5-v1'], sid: ['s'], stype: ['scaffold'] } },
    } },
  }) })))
  const result = await loadBevelSource({ ...source, featureId: 'f' }, {})
  expect(fetch.mock.calls[0][0]).toContain('compact_geometry=true')
  expect(result.component.nucleotides_compact).toBeUndefined()
  expect(result.component.nucleotides[0]).toMatchObject({ helix_id: 'h', bp_index: 3,
    backbone_position: [1, 2, 3], slab_position: [4, 5, 6], strand_id: 's' })
})
