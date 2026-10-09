// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { createVRFeatureLog } from './vr_feature_log.js'

function harness() {
  let state = { title: 'Feature history', identity: 'part:one', revision: 1, busy: false, rows: [{ id: 'r:0', label: 'F0', enabled: true }], targets: [] }
  const activate = vi.fn(), request = vi.fn(async () => ({ ok: true })), refresh = vi.fn(async () => ({ published: true }))
  let subscriber
  const adapter = createVRFeatureLog({ panel: () => ({ vr: { snapshot: () => state, activate } }), store: { subscribe: fn => { subscriber = fn;return vi.fn() } }, refresh, request, onError: vi.fn() })
  return { adapter, activate, request, refresh, set: value => { state = { ...state, ...value } }, emit: (...args) => subscriber(...args), sent: () => JSON.parse(request.mock.calls.at(-1)[1].body) }
}
describe('VR history transport', () => {
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
