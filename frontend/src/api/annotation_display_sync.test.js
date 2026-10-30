import { afterEach, expect, it, vi } from 'vitest'
import { saveAnnotations, resetRevisionWatermark } from './client.js'
import { store } from '../state/store.js'
import { nadocBroadcast } from '../shared/broadcast.js'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('saves annotations and syncs sibling tabs without invalidating the local simulation', async () => {
  resetRevisionWatermark()
  const geometry = [{ backbone_position: [10, 20, 30] }]
  store.setState({ currentDesign: { id: 'annotation-sim', annotations: [] }, currentGeometry: geometry })
  const annotations = [{ id: 'a', text: 'Protein', highlight: true, highlight_type: 'silhouette' }]
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, headers: new Headers(),
    json: async () => ({ design_id: 'annotation-sim', revision: 1, annotations, annotations_enabled: true }) })))
  const broadcast = vi.spyOn(nadocBroadcast, 'emit')
  const invalidate = vi.fn()
  window.addEventListener('nadoc:design-changed', invalidate)
  try {
    expect(await saveAnnotations({ annotations, enabled: true })).toMatchObject({ annotations })
    expect(store.getState().currentGeometry).toBe(geometry)
    expect(broadcast).toHaveBeenCalledWith('design-changed', expect.objectContaining({ metadata_only: true, geometry_unchanged: true }))
    expect(invalidate).not.toHaveBeenCalled()
  } finally { window.removeEventListener('nadoc:design-changed', invalidate) }
})
