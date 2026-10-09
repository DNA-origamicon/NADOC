import { describe, it, expect, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initNanoparticleAttach } from './nanoparticle_attach.js'

function setup() {
  const filters = { scaffold: true, staples: true, strands: true, overhangs: false }
  const store = createMockStore({ currentDesign: { id: 'd', overhangs: [{ id: 'o' }] },
    selectableTypes: filters, toolFilters: { overhangLocations: false }, selection: { items: [] } })
  const api = { attachNanoparticleToOverhang: vi.fn().mockResolvedValue({}) }
  const selectionController = { clear: () => store.setState({ selection: { items: [] } }), select: vi.fn() }
  const notify = vi.fn()
  return { store, api, filters, notify, selectionController,
    tool: initNanoparticleAttach({ store, api, selectionController, notify }) }
}

describe('Attach nanoparticle picker', () => {
  it('accepts only an overhang and restores filters after a single submission', async () => {
    const t = setup()
    t.tool.begin('np')
    expect(t.store.getState().selectableTypes.strands).toBe(false)
    expect(t.store.getState().selectableTypes.overhangs).toBe(true)
    t.store.setState({ selection: { items: [{ kind: 'strand', id: 's' }] } })
    expect(t.api.attachNanoparticleToOverhang).not.toHaveBeenCalled()
    t.store.setState({ selection: { items: [{ kind: 'overhang', id: 'o' }] } })
    await vi.waitFor(() => expect(t.selectionController.select).toHaveBeenCalledWith({ kind: 'nanoparticle', id: 'np' }))
    expect(t.api.attachNanoparticleToOverhang).toHaveBeenCalledExactlyOnceWith('np', 'o')
    expect(t.store.getState().selectableTypes).toEqual(t.filters)
    t.tool.dispose()
  })
  it('cancels on Escape and document change without binding', () => {
    const t = setup()
    t.tool.begin('np')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(t.store.getState().selectableTypes).toEqual(t.filters)
    t.tool.begin('np')
    t.store.setState({ currentDesign: { id: 'other' } })
    expect(t.store.getState().selectableTypes).toEqual(t.filters)
    expect(t.api.attachNanoparticleToOverhang).not.toHaveBeenCalled()
    t.tool.dispose()
  })
  it('restores selection tools and reports an infeasible attachment', async () => {
    const t = setup()
    t.api.attachNanoparticleToOverhang.mockRejectedValue(new Error('Occupied overhang'))
    t.tool.begin('np')
    t.store.setState({ selection: { items: [{ kind: 'overhang', id: 'o' }] } })
    await vi.waitFor(() => expect(t.notify).toHaveBeenCalledWith('Occupied overhang', expect.objectContaining({ severity: 'error' })))
    expect(t.store.getState().selectableTypes).toEqual(t.filters)
    t.tool.dispose()
  })
})
