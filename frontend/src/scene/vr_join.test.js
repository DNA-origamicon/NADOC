import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createVRJoin, vrJoinPose, vrJoinSegments, vrJoinSites } from './vr_join.js'
import { createVRToolTransactionCoordinator } from './vr_tool_transaction.js'
import { clusterJoinNativeSignature } from './cluster_join_document.js'

const matrix = (x = 0) => new THREE.Matrix4().makeTranslation(x, 0, 0).toArray()
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const tick = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); await vi.advanceTimersByTimeAsync(150) }
function harness() {
  vi.useFakeTimers()
  let state = { currentDesign: { id: 'part', feature_log: [], cluster_transforms: [{ id: 'A' }, { id: 'B' }] } }
  let revision = 7, document = 'doc'
  const result = body => ({ valid: true, design_id: 'part', revision: 7, preview_token: `token-${body.world_translation[0]}`,
    connection_count: 2, bridges: [{ points: [[0, 0, 0], [1, 0, 0], [2, 0, 0]] }] })
  const api = {
    getClusterJoinSites: vi.fn(async () => ({ design_id: 'part', revision: 7,
      clusters: ['A', 'B'].map(cluster_id => ({ cluster_id, eligible: true })),
      sites: ['A', 'B'].map(cluster_id => ({ cluster_id, position: [0, 0, 0], normal: [1, 0, 0] })) })),
    previewClusterJoin: vi.fn(async body => result(body)),
    sendVRJoinFeedback: vi.fn(async () => ({ published: true })),
    currentRevisionWatermark: () => revision,
    applyClusterJoin: vi.fn(async () => ({ design: { ...state.currentDesign, feature_log: [{ id: 'joined' }] }, revision: 8 })),
    _syncFromDesignResponse: vi.fn(async response => { state = { ...state, currentDesign: response.design }; revision = response.revision; return response }),
    refreshNativeVRScene: vi.fn(async () => ({ published: true })),
    undo: vi.fn(async ({ onCommitted } = {}) => {
      state = { ...state, currentDesign: { ...state.currentDesign, feature_log: [] } }; revision++
      const response = { design: state.currentDesign, revision }; onCommitted?.(response); return response
    }),
  }
  const sendFeedback = vi.fn(async () => ({ published: true })), onError = vi.fn(), setSelectionLevel = vi.fn()
  const transaction = createVRToolTransactionCoordinator({ getState: () => state, undoDesign: api.undo })
  const join = createVRJoin({ api, getState: () => state, getDocumentToken: () => document,
    resolveTarget: target => target.selectionKind === 'cluster' && ['A', 'B'].includes(target.identity)
      ? { selectedRef: { kind: 'cluster', id: target.identity } } : null,
    transaction, sendFeedback, onError, setSelectionLevel })
  const event = (action = 'preview', sequence = 1, x = 0, id = 'B') => ({ type: 'tool', mode: 'join', action, sequence,
    targetIdentity: id, targetKind: 'cluster', targetOwnerTokens: [`owner-${id}`], transformMatrix: matrix(x), transformSequence: sequence })
  const transform = (x, sequence) => join.handle({ type: 'tool_transform', sequence, matrix: matrix(x) })
  return { join, api, event, transform, result, sendFeedback, onError, setSelectionLevel, transaction,
    changeDocument: () => { document = 'other-doc' }, changeRevision: () => { revision++ },
    changeDesign: () => { state = { ...state, currentDesign: { ...state.currentDesign, cluster_transforms: [{ id: 'changed' }] } } },
    changeMetadata: () => { state = { ...state, currentDesign: { ...state.currentDesign, name: 'Saved copy' } } },
    state: () => state }
}
afterEach(() => vi.useRealTimers())

describe('VR Join world pose and bounded render data', () => {
  it('shares desktop document retirement rules, preserving harmless metadata only', () => {
    const design = { name: 'First', helices: [{ id: 'h' }], cluster_transforms: [{ id: 'A' }] }
    expect(clusterJoinNativeSignature({ ...design, name: 'Saved', feature_log: [{ id: 'history' }] })).toBe(clusterJoinNativeSignature(design))
    expect(clusterJoinNativeSignature({ ...design, helices: [] })).not.toBe(clusterJoinNativeSignature(design))
  })
  it('preserves a rigid world rotation and translation, rejecting shear, scale and reflection', () => {
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 3)
    const rigid = new THREE.Matrix4().compose(new THREE.Vector3(2, 3, 4), q, new THREE.Vector3(1, 1, 1)).toArray()
    expect(vrJoinPose(rigid).world_translation).toEqual([2, 3, 4])
    expect(vrJoinPose(rigid).world_rotation[2]).toBeCloseTo(0.5)
    for (const invalid of [null, [1], matrix().map((v, i) => i === 0 ? 2 : v), matrix().map((v, i) => i === 0 ? -1 : v), matrix().map((v, i) => i === 4 ? 0.1 : v)]) expect(vrJoinPose(invalid)).toBeNull()
  })
  it('publishes only finite sites with a bounded moving/fixed catalog', () => {
    const sites = Array.from({ length: 10000 }, (_, i) => ({ cluster_id: i % 2 ? 'A' : 'B', position: [i, 0, 0], normal: [1, 0, 0] }))
    const hints = vrJoinSites([...sites, { position: [NaN, 0, 0] }], 'B')
    expect(hints).toHaveLength(8192)
    expect(hints.filter(site => site.moving)).toHaveLength(4096)
    expect(hints.at(-1).moving).toBe(false)
  })
  it('converts complete bridge polylines to bounded finite line segments', () => {
    expect(vrJoinSegments([{ points: [[0, 0, 0], [1, 2, 3], [NaN, 0, 0]] }])).toEqual([{ a: [0, 0, 0], b: [1, 2, 3] }])
    expect(vrJoinSegments([{ points: Array.from({ length: 9000 }, (_, i) => [i, 0, 0]) }])).toHaveLength(128)
  })
})

describe('VR Join controller', () => {
  it('activates cluster selection and previews the desktop free join without mutating design', async () => {
    const h = harness(), original = h.state().currentDesign
    h.join.handle(h.event('activate', 1)); await tick()
    expect(h.setSelectionLevel).toHaveBeenCalledWith('cluster')
    expect(h.api.previewClusterJoin).toHaveBeenCalledWith(expect.objectContaining({ mode: 'free', moving_cluster_id: 'B', expected_revision: 7 }), expect.anything())
    expect(h.api.sendVRJoinFeedback.mock.calls.some(([value]) => value.sites.length === 2)).toBe(true)
    expect(h.join.getState()).toMatchObject({ valid: true, connectionCount: 2 })
    expect(h.state().currentDesign).toBe(original)
    expect(h.api.applyClusterJoin).not.toHaveBeenCalled()
  })
  it('coalesces continuous motion with one in-flight preview and rejects old results', async () => {
    const h = harness(), first = deferred()
    h.api.previewClusterJoin.mockReturnValueOnce(first.promise)
    h.join.handle(h.event()); await tick()
    for (let i = 1; i <= 100; i++) h.transform(i, i + 1)
    await tick()
    expect(h.api.previewClusterJoin).toHaveBeenCalledTimes(1)
    first.resolve(h.result({ world_translation: [0, 0, 0] })); await tick()
    expect(h.api.previewClusterJoin).toHaveBeenCalledTimes(2)
    expect(h.api.previewClusterJoin.mock.calls[1][0].world_translation).toEqual([100, 0, 0])
    expect(h.join.getState()).toMatchObject({ valid: true, transformSequence: 101 })
  })
  it('Cancel retires late previews and never writes pose or topology', async () => {
    const h = harness(), pending = deferred(), design = h.state().currentDesign
    h.api.previewClusterJoin.mockReturnValueOnce(pending.promise)
    h.join.handle(h.event()); await tick(); h.join.handle(h.event('cancel', 2))
    pending.resolve(h.result({ world_translation: [0, 0, 0] })); await tick()
    expect(h.join.getState()).toMatchObject({ active: false, valid: false, status: 'cancelled' })
    expect(h.state().currentDesign).toBe(design)
    expect(h.api.applyClusterJoin).not.toHaveBeenCalled()
  })
  it('Apply validates the exact final pose, commits once and refreshes history and VR', async () => {
    const h = harness()
    h.join.handle(h.event()); await tick()
    h.join.handle(h.event('confirm', 2, 7)); h.join.handle(h.event('confirm', 3, 7)); await tick()
    expect(h.api.applyClusterJoin).toHaveBeenCalledTimes(1)
    expect(h.api.applyClusterJoin.mock.calls[0][0]).toMatchObject({ world_translation: [7, 0, 0], preview_token: 'token-7' })
    expect(h.api._syncFromDesignResponse).toHaveBeenCalledOnce()
    expect(h.api.refreshNativeVRScene).toHaveBeenCalledWith({ expected_design_id: 'part', expected_revision: 8 })
    expect(h.transaction.snapshot().committed).toMatchObject({ tool: 'join', featureLogEntryId: 'joined' })
    expect(h.join.getState()).toMatchObject({ active: false, busy: false, status: 'applied' })
    h.join.handle(h.event('undo', 4)); await tick()
    expect(h.api.undo).toHaveBeenCalledOnce()
    expect(h.api.refreshNativeVRScene).toHaveBeenLastCalledWith({ expected_design_id: 'part', expected_revision: 9 })
  })
  it.each(['changeDocument', 'changeRevision', 'changeDesign'])('refuses Apply after %s', async change => {
    const h = harness()
    h.join.handle(h.event()); await tick(); h[change]()
    h.join.handle(h.event('confirm', 2)); await tick()
    expect(h.api.applyClusterJoin).not.toHaveBeenCalled()
    expect(h.join.getState().valid).toBe(false)
  })
  it('refuses a changed action target and never widens it to another cluster', async () => {
    const h = harness()
    h.join.handle(h.event()); await tick(); h.join.handle(h.event('confirm', 2, 0, 'A')); await tick()
    expect(h.api.applyClusterJoin).not.toHaveBeenCalled()
  })
  it('preserves the proposed pose across metadata-only save acknowledgements', async () => {
    const h = harness()
    h.join.handle(h.event('preview', 1, 4)); await tick(); h.changeMetadata()
    h.join.handle(h.event('confirm', 2, 4)); await tick()
    expect(h.api.applyClusterJoin).toHaveBeenCalledOnce()
    expect(h.api.applyClusterJoin.mock.calls[0][0].world_translation).toEqual([4, 0, 0])
  })
  it('refreshes a saved revision while retaining the current rigid preview pose', async () => {
    const h = harness()
    h.join.handle(h.event('preview', 1, 4)); await tick(); h.changeMetadata(); h.changeRevision()
    h.api.getClusterJoinSites.mockResolvedValue({ design_id: 'part', revision: 8, clusters: [{ cluster_id: 'B', eligible: true }], sites: [] })
    h.api.previewClusterJoin.mockImplementation(async body => ({ ...h.result(body), revision: 8 }))
    await h.join.publish(); await tick()
    expect(h.api.previewClusterJoin).toHaveBeenLastCalledWith(expect.objectContaining({ world_translation: [4, 0, 0], expected_revision: 8 }), expect.anything())
    expect(h.join.getState().valid).toBe(true)
  })
  it('locks retries after an ambiguous mutation response', async () => {
    const h = harness()
    h.api.applyClusterJoin.mockRejectedValueOnce(new TypeError('Connection lost'))
    h.join.handle(h.event()); await tick(); h.join.handle(h.event('confirm', 2)); await tick()
    expect(h.join.getState().needsResync).toBe(true)
    h.changeMetadata()
    h.join.handle(h.event('confirm', 3)); await tick()
    expect(h.api.applyClusterJoin).toHaveBeenCalledOnce()
    expect(h.join.getState().status).toBe('failed')
  })
  it('recovers ambiguous outcomes only after an authoritative reload and native scene refresh', async () => {
    const h = harness()
    h.api.applyClusterJoin.mockRejectedValueOnce(new TypeError('Connection lost'))
    h.join.handle(h.event()); await tick(); h.join.handle(h.event('confirm', 2)); await tick()
    h.api.getDesign = vi.fn(async () => ({ design: h.state().currentDesign }))
    h.join.handle(h.event('activate', 3)); await tick()
    expect(h.api.getDesign).toHaveBeenCalledOnce()
    expect(h.api.refreshNativeVRScene).toHaveBeenCalledWith({ expected_design_id: 'part', expected_revision: 7 })
    expect(h.join.getState()).toMatchObject({ needsResync: false, valid: false, status: 'ready', targetId: null })
    expect(h.api.applyClusterJoin).toHaveBeenCalledOnce()
  })
  it('retires a session ending during Apply and accepts sequence 1 on the next session', async () => {
    const h = harness(), mutation = deferred()
    h.api.applyClusterJoin.mockReturnValueOnce(mutation.promise)
    h.join.handle(h.event()); await tick(); h.join.handle(h.event('confirm', 2)); await tick()
    expect(h.api.applyClusterJoin).toHaveBeenCalledOnce()
    h.join.handle({ type: 'native_session_end' })
    mutation.resolve({ design: { ...h.state().currentDesign, feature_log: [{ id: 'joined' }] }, revision: 8 })
    await tick()
    expect(h.join.getState()).toMatchObject({ active: false, busy: false, sequence: 0, valid: false })
    expect(h.sendFeedback.mock.calls.some(([, status]) => status === 'succeeded')).toBe(false)
    h.join.handle({ type: 'tool', mode: 'join', action: 'activate', sequence: 1, targetKind: 'none' })
    expect(h.join.getState()).toMatchObject({ active: true, sequence: 1, status: 'ready' })
    expect(h.state().currentDesign.feature_log).toEqual([{ id: 'joined' }])
  })
  it('does not preview ineligible clusters', async () => {
    const h = harness()
    h.api.getClusterJoinSites.mockResolvedValue({ design_id: 'part', revision: 7, clusters: [{ cluster_id: 'B', eligible: false, reason: 'No attachment sites' }], sites: [] })
    h.join.handle(h.event()); await tick()
    expect(h.api.previewClusterJoin).not.toHaveBeenCalled()
    expect(h.join.getState()).toMatchObject({ status: 'invalid', valid: false })
  })
})
