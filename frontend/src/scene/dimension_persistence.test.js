import { afterEach, describe, it, expect, vi } from 'vitest'
import { initDimensionPersistence } from './dimension_persistence.js'

afterEach(() => vi.useRealTimers())
function fixture() {
  let state = { currentDesign: { id: 'a', dimensions: [{ id: 'saved' }] } }
  const listeners = new Set()
  return { getState: () => state, subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn) },
    set(value) { state = value; listeners.forEach(fn => fn()) } }
}
describe('dimension persistence', () => {
  it('restores saved records, follows document changes and stops polling on dispose', async () => {
    vi.useFakeTimers()
    const store = fixture(), onRecords = vi.fn(), load = vi.fn().mockResolvedValue({})
    const binding = initDimensionPersistence({ store, transport: { load }, onRecords })
    expect(onRecords).toHaveBeenLastCalledWith([{ id: 'saved' }])
    store.set({ assemblyActive: true, currentAssembly: { id: 'b', dimensions: [{ id: 'assembly' }] } })
    expect(onRecords).toHaveBeenLastCalledWith([{ id: 'assembly' }])
    await vi.advanceTimersByTimeAsync(1000)
    expect(load).toHaveBeenLastCalledWith('assembly', 'b')
    binding.dispose(); const count = load.mock.calls.length
    await vi.advanceTimersByTimeAsync(2000); expect(load).toHaveBeenCalledTimes(count)
  })
  it('serializes writes against their originating document and reports failures', async () => {
    vi.useFakeTimers()
    const store = fixture(), save = vi.fn().mockRejectedValue(new Error('offline')), error = vi.fn()
    const binding = initDimensionPersistence({ store, transport: { load: async () => {}, save, capture: () => ({ docId: 'tab-a' }) }, onRecords: () => {}, onError: error })
    const pending = binding.change([{ id: 'new' }])
    store.set({ currentDesign: { id: 'other', dimensions: [] } })
    await pending
    expect(save).toHaveBeenCalledWith('design', 'a', [{ id: 'new' }], [], { docId: 'tab-a' })
    expect(error).toHaveBeenCalledTimes(1)
    binding.dispose()
  })
  it('retains failed writes and retries before loading remote records', async () => {
    vi.useFakeTimers()
    const store = fixture(), onRecords = vi.fn(), load = vi.fn().mockResolvedValue({})
    const save = vi.fn().mockRejectedValueOnce(new Error('offline')).mockImplementation(async () => {
      store.set({ currentDesign: { id: 'a', dimensions: [{ id: 'new' }] } })
    })
    const binding = initDimensionPersistence({ store, transport: { load, save }, onRecords })
    await binding.change([{ id: 'new' }])
    onRecords.mockClear()
    await vi.advanceTimersByTimeAsync(1000)
    expect(save).toHaveBeenCalledTimes(2)
    expect(onRecords).toHaveBeenLastCalledWith([{ id: 'new' }])
    binding.dispose()
  })

})
