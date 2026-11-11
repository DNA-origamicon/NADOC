import { expect, it, vi } from 'vitest'
import { createZoomVolumeAPI } from './zoom_volume_endpoints.js'

it.each([false, true])('serializes rapid magnification changes and pins document context (assembly=%s)', async assembly => {
  const state = { currentDesign: { id: 'p' }, currentAssembly: { id: 'a' } }
  let release
  const request = vi.fn().mockImplementationOnce(() => new Promise(resolve => { release = resolve })).mockResolvedValue({ revision: 2 })
  const tracker = { acceptMetadata: vi.fn() }, persist = vi.fn()
  const save = createZoomVolumeAPI({ store: { getState: () => state }, request, captureContext: () => ({ docId: 'tab' }),
    designRevisions: tracker, assemblyRevisions: tracker, persistDesign: persist, persistAssembly: persist, signalDesignChanged: vi.fn() })
  const first = save([{ id: 'z', zoom_step: 1 }], assembly), second = save([{ id: 'z', zoom_step: 2 }], assembly)
  await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1))
  release({ revision: 1 }); await Promise.all([first, second])
  expect(request.mock.calls.map(c => c[2].volumes[0].zoom_step)).toEqual([1, 2])
  expect(request.mock.calls[1][1]).toBe(`/${assembly ? 'assembly' : 'design'}/zoom-volumes`)
  expect(request.mock.calls[1][3].docId).toBe('tab')
  expect(persist).toHaveBeenCalledTimes(2)
})
