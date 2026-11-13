import { expect, it, vi } from 'vitest'
import { webcrypto, createHash } from 'node:crypto'
import { createHistoryBodyCache } from './history_body_cache.js'
import { _mergeFeatureLogPayloads } from './client.js'

it('hashes the same length-prefixed bytes as the server and invalidates changed bodies', async () => {
  vi.stubGlobal('crypto', webcrypto)
  try {
    const digest = createHistoryBodyCache()
    const entry = { id: 'e', post_state_gz_b64: 'snapshot' }
    const design = { feature_log: [entry] }
    const expected = createHash('sha256').update('0:0:8:snapshot').digest('hex')
    expect(await digest(design)).toEqual({ e: expected })
    expect(await digest(design)).toEqual({ e: expected })
    entry.post_state_gz_b64 = 'older'
    expect((await digest(design)).e).not.toBe(expected)
  } finally { vi.unstubAllGlobals() }
})
it('does not refill an intentionally cleared body under the same ID', () => {
  const previous = { feature_log: [{ id: 'e', post_state_gz_b64: 'newer' }] }
  const incoming = { feature_log: [{ id: 'e', post_state_gz_b64: '' }] }
  expect(_mergeFeatureLogPayloads(incoming, previous, []).feature_log[0].post_state_gz_b64).toBe('')
  expect(_mergeFeatureLogPayloads(incoming, previous, ['e']).feature_log[0].post_state_gz_b64).toBe('newer')
})

it('undo reconstructs from its acknowledged source even if another response updated the cache meanwhile', async () => {
  const { undo, resetRevisionWatermark } = await import('./client.js')
  const { store } = await import('../state/store.js')
  const design = body => ({ id: 'cache-race', helices: [], strands: [], deformations: [],
    extensions: [], overhangs: [], feature_log: [{ id: 'e', post_state_gz_b64: body }] })
  let complete
  const fetch = vi.fn(() => new Promise(resolve => { complete = resolve }))
  vi.stubGlobal('fetch', fetch)
  resetRevisionWatermark()
  store.setState({ currentDesign: design('acknowledged'), currentGeometry: [] })
  try {
    const pending = undo()
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    store.setState({ currentDesign: design('intervening') })
    complete({ ok: true, status: 200, headers: new Headers(), json: async () => ({
      design: design(''), revision: 3, nucleotides: [], helix_axes: [],
      feature_log_payloads_partial: true, feature_log_reused_entry_ids: ['e'],
    }) })
    await pending
    expect(store.getState().currentDesign.feature_log[0].post_state_gz_b64).toBe('acknowledged')
    window.dispatchEvent(new Event('pagehide'))
  } finally { store.setState({ currentDesign: null }); vi.unstubAllGlobals() }
})

it('uses server content tokens without adding fields to authored history', async () => {
  const { receiveHistoryBodyDigests, inheritHistoryBodyDigest } = await import('./history_body_cache.js')
  vi.stubGlobal('crypto', webcrypto)
  try {
    const previous = { id: 'e', post_state_gz_b64: 'snapshot' }
    receiveHistoryBodyDigests({ feature_log: [previous] }, { e: 'server-digest' })
    const reconstructed = { ...previous }
    inheritHistoryBodyDigest(reconstructed, previous)
    expect(await createHistoryBodyCache()({ feature_log: [reconstructed] })).toEqual({ e: 'server-digest' })
    expect(reconstructed).toEqual({ id: 'e', post_state_gz_b64: 'snapshot' })
  } finally { vi.unstubAllGlobals() }
})


it('retains a removed redo body for one transition without modifying authored history', async () => {
  const cache = createHistoryBodyCache()
  const old = { id: 'edit', post_state_gz_b64: 'recovery' }
  const edited = { id: 'part', feature_log: [old] }
  cache.source(edited, 1)
  const undone = { id: 'part', feature_log: [] }
  const recovery = cache.source(undone, 1)
  expect(recovery.feature_log).toEqual([old])
  expect(undone.feature_log).toEqual([])
  const response = { feature_log: [{ id: 'edit', post_state_gz_b64: '' }] }
  expect(_mergeFeatureLogPayloads(response, recovery, ['edit']).feature_log).toEqual([old])
  // Retention is bounded to the last original source, not an accumulating union.
  expect(cache.source(undone, 1).feature_log).toEqual([])
})

it('prefers current same-ID bodies and drops retained bodies across document scopes', () => {
  const cache = createHistoryBodyCache()
  const old = { id: 'part', feature_log: [{ id: 'e', post_state_gz_b64: 'old' }] }
  const current = { id: 'part', feature_log: [{ id: 'e', post_state_gz_b64: '' }] }
  cache.source(old, 1)
  expect(cache.source(current, 1).feature_log).toEqual(current.feature_log)
  cache.source(old, 1)
  expect(cache.source({ id: 'part', feature_log: [] }, 2).feature_log).toEqual([])
  cache.source(old, 2)
  expect(cache.source({ id: 'other', feature_log: [] }, 2).feature_log).toEqual([])
})
