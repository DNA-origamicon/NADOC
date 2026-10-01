import { it, expect, vi, afterEach } from 'vitest'
import { store } from '../state/store.js'
import { getDesignSurfaceBin, getRegionSurface, getInstanceSurfaceGeometry } from './client.js'
afterEach(() => { store.setState({ presentationActive: false }); vi.unstubAllGlobals() })
it('blocks detailed design, region and assembly surfaces before sending any request during presentations', async () => {
  const request = vi.fn(); vi.stubGlobal('fetch', request)
  store.setState({ presentationActive: true })
  await expect(getDesignSurfaceBin({ detail: 'chimerax' })).rejects.toThrow('unavailable during presentations')
  await expect(getRegionSurface([], { detail: 'fine' })).rejects.toThrow('unavailable during presentations')
  await expect(getInstanceSurfaceGeometry('part', 'strand', .06, .2, 'chimerax')).rejects.toThrow('unavailable during presentations')
  expect(request).not.toHaveBeenCalled()
})
