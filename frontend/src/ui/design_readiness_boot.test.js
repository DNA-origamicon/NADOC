import { describe, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { readinessBootDocument, restoreReadinessDocument } from './design_readiness_boot.js'

describe('explicit readiness navigation boot', () => {
  it('requires an explicit document and simulation request, without competing boot actions', () => {
    expect(readinessBootDocument('http://localhost/?doc=d&readiness=simulation')).toBe('d')
    expect(readinessBootDocument('http://localhost/?doc=__default__&readiness=simulation')).toBe('__default__')
    for (const query of ['doc=d', 'readiness=simulation', 'doc=d&readiness=staple_routing', 'doc=d&readiness=simulation&new=part', 'doc=d&readiness=simulation&open=part.nadoc', 'doc=d&readiness=simulation&part-instance=a']) {
      expect(readinessBootDocument(`http://localhost/?${query}`)).toBeNull()
    }
    expect(readinessBootDocument('http://localhost/?doc=d&readiness=simulation', 'cadnano')).toBeNull()
  })

  function fixture() {
    const design = { id: 'd', metadata: { name: 'Arm' } }
    const store = createMockStore({ currentDesign: null })
    const calls = []
    const api = {
      getDesign: vi.fn(async () => { calls.push('design'); store.setState({ currentDesign: design }); return { design } }),
      getGeometry: vi.fn(async () => { calls.push('geometry'); return { nucleotides: [] } }),
    }
    return { api, store, href: 'http://localhost/?doc=d&readiness=simulation', document: { title: '' }, onRestored: vi.fn(() => calls.push('ready')), calls }
  }

  it('hydrates only through the two read endpoints and unlocks controls after geometry', async () => {
    const deps = fixture()
    expect(await restoreReadinessDocument(deps)).toBe(true)
    expect(deps.calls).toEqual(['design', 'geometry', 'ready'])
    expect(deps.document.title).toBe('NADOC 3D — Arm')
  })

  it('does not replace a document already open in this tab', async () => {
    const deps = fixture()
    deps.store.setState({ currentDesign: { id: 'other' } })
    expect(await restoreReadinessDocument(deps)).toBe(false)
    expect(deps.api.getDesign).not.toHaveBeenCalled()
  })

  it('does not unlock controls or create a new design when the source is missing', async () => {
    const deps = fixture()
    deps.api.getDesign.mockResolvedValue(null)
    await expect(restoreReadinessDocument(deps)).rejects.toThrow('no longer available')
    expect(deps.api.getGeometry).not.toHaveBeenCalled()
    expect(deps.onRestored).not.toHaveBeenCalled()
  })

  it('keeps navigation gated if geometry fails or the host is disposed during restoration', async () => {
    const deps = fixture()
    deps.api.getGeometry.mockResolvedValue(null)
    await expect(restoreReadinessDocument(deps)).rejects.toThrow('geometry')
    expect(deps.onRestored).not.toHaveBeenCalled()
    const closed = fixture()
    expect(await restoreReadinessDocument({ ...closed, isDisposed: () => true })).toBe(false)
    expect(closed.api.getGeometry).not.toHaveBeenCalled()
    expect(closed.onRestored).not.toHaveBeenCalled()
  })

  it('does not reveal or rename a different document selected during the read', async () => {
    const deps = fixture()
    deps.api.getGeometry.mockImplementation(async () => {
      deps.store.setState({ currentDesign: { id: 'replacement' } })
      return { nucleotides: [] }
    })
    await expect(restoreReadinessDocument(deps)).rejects.toThrow('document changed')
    expect(deps.onRestored).not.toHaveBeenCalled()
    expect(deps.document.title).toBe('')
  })
})
