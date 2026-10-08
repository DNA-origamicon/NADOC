import { describe, expect, it } from 'vitest'
import { _mergeFeatureLogPayloads } from './client.js'

describe('slim mutation history merge', () => {
  it('restores old bodies while leaving the new entry payload intact', () => {
    const previous = { feature_log: [
      { id: 'old', design_snapshot_gz_b64: 'old-pre', post_state_gz_b64: 'old-post' },
    ] }
    const incoming = { feature_log: [
      { id: 'old', design_snapshot_gz_b64: '', post_state_gz_b64: '' },
      { id: 'new', design_snapshot_gz_b64: 'new-pre', post_state_gz_b64: 'new-post' },
    ] }

    expect(_mergeFeatureLogPayloads(incoming, previous).feature_log).toEqual([
      { id: 'old', design_snapshot_gz_b64: 'old-pre', post_state_gz_b64: 'old-post' },
      { id: 'new', design_snapshot_gz_b64: 'new-pre', post_state_gz_b64: 'new-post' },
    ])
  })
})

import { vi, afterEach } from 'vitest'
import { seekFeatures, resetRevisionWatermark } from './client.js'
import { store } from '../state/store.js'
afterEach(() => vi.unstubAllGlobals())
it.each(['positions_only', 'cluster_only'])('%s seeks retain recovery bodies', async diff_kind => {
  resetRevisionWatermark()
  const previous = { id: 'seek-body-test', helices: [], strands: [], feature_log: [
    { id: 'snapshot', feature_type: 'snapshot', design_snapshot_gz_b64: 'pre', post_state_gz_b64: 'post' },
  ] }
  store.setState({ currentDesign: previous, currentGeometry: [], currentHelixAxes: {}, featureSeekPending: true })
  const incoming = { ...previous, feature_log: [{ ...previous.feature_log[0], design_snapshot_gz_b64: '', post_state_gz_b64: '' }] }
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, headers: { get: () => null },
    json: async () => ({ design: incoming, revision: 2, diff_kind, feature_log_payloads_partial: true }) })))
  await seekFeatures(0)
  expect(store.getState().currentDesign.feature_log[0].post_state_gz_b64).toBe('post')
  expect(store.getState().currentDesign.feature_log[0].design_snapshot_gz_b64).toBe('pre')
  store.setState({ featureSeekPending: false })
})
