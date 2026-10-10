// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { createVRFeatureLog } from './vr_feature_log.js'

function harness(options = {}) {
  let state = { title: 'Feature history', identity: 'part:one', revision: 1, busy: false, rows: [{ id: 'r:0', label: 'F0', enabled: true }], targets: [] }
  const activate = vi.fn(), request = vi.fn(async () => ({ ok: true })), refresh = vi.fn(async () => ({ published: true }))
  let subscriber
  const adapter = createVRFeatureLog({ panel: () => ({ vr: { snapshot: () => state, activate } }), store: { subscribe: fn => { subscriber = fn;return vi.fn() } }, refresh, request, onError: vi.fn(), ...options })
  return { adapter, activate, request, refresh, set: value => { state = { ...state, ...value } }, emit: (...args) => subscriber(...args), sent: () => JSON.parse(request.mock.calls.at(-1)[1].body) }
}
describe('VR history transport', () => {
  it('publishes the post-seek design identity and revision through the production refresh API', async () => {
    vi.useFakeTimers()
    let currentDesign = { id: 'part-before' }, revision = 3, subscriber
    const api = { currentRevisionWatermark: () => revision, refreshNativeVRScene: vi.fn(async () => ({ published: true })) }
    const h = harness({ api, refresh: undefined, store: {
      getState: () => ({ currentDesign }), subscribe: fn => { subscriber = fn; return vi.fn() },
    } })
    try {
      await h.adapter.publish()
      h.activate.mockImplementation(async () => {
        const previous = { currentDesign }
        currentDesign = { id: 'part-after', feature_log_cursor: 2 }; revision = 4
        subscriber({ currentDesign }, previous)
      })
      await h.adapter.activate({ sequence: 1, version: h.sent().version, id: 'r:0' })
      await vi.advanceTimersByTimeAsync(130)
      expect(api.refreshNativeVRScene).toHaveBeenCalledExactlyOnceWith({ expected_design_id: 'part-after', expected_revision: 4 })
      expect(h.sent().status).not.toContain('failed')
    } finally { h.adapter.dispose(); vi.useRealTimers() }
  })

  it('rejects stale target revisions and duplicate events', async () => {
    const h = harness();await h.adapter.publish();const old = h.sent()
    h.set({ identity: 'part:two' });await h.adapter.activate({ sequence: 1, version: old.version, id: 'r:0' });expect(h.activate).not.toHaveBeenCalled()
    const current = h.sent();await h.adapter.activate({ sequence: 2, version: current.version, id: 'r:0' });expect(h.activate).toHaveBeenCalledOnce()
    await h.adapter.activate({ sequence: 2, version: current.version, id: 'r:0' });expect(h.activate).toHaveBeenCalledOnce();h.adapter.dispose()
  })
  it('does not activate during scene refresh and refreshes committed desktop changes', async () => {
    vi.useFakeTimers()
    const h = harness();await h.adapter.publish();await h.adapter.activate({ sequence: 1, version: h.sent().version, id: 'r:0' })
    h.emit({ currentDesign: {} }, { currentDesign: {} });await vi.advanceTimersByTimeAsync(130)
    expect(h.refresh).toHaveBeenCalledOnce();h.adapter.dispose();vi.useRealTimers()
  })
  it('does not refresh unrelated desktop work after session reset', async () => {
    vi.useFakeTimers();const h = harness();await h.adapter.publish();h.adapter.reset()
    h.emit({ currentDesign: {} }, { currentDesign: {} });await vi.advanceTimersByTimeAsync(200)
    expect(h.refresh).not.toHaveBeenCalled();h.adapter.dispose();vi.useRealTimers()
  })
})
