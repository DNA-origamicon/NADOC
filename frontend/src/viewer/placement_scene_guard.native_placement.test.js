import { afterEach, beforeEach, expect, it, vi } from 'vitest'

vi.mock('three', async importOriginal => {
  const actual = await importOriginal()
  return { ...actual, WebGLRenderer: vi.fn(function () {
    this.xr = { isPresenting: false, getSession: vi.fn() }
    for (const name of ['setSize', 'setPixelRatio', 'setClearColor', 'setAnimationLoop', 'dispose', 'render', 'clear', 'setRenderTarget']) this[name] = vi.fn()
  }) }
})

beforeEach(() => {
  vi.resetModules()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  document.body.innerHTML = '<div><canvas></canvas></div>'
})
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })

it.each([false, true])('[native-placement] runtime blocks desktop, XR, updates, and exports even when buffer clear throws (%s)', async clearThrows => {
  const { initScene } = await import('./runtime.js')
  const { Scene, Mesh, BoxGeometry, MeshBasicMaterial } = await import('three')
  const { installPlacementSceneGuard, assertPlacementExportSafe } = await import('./placement_scene_guard.js')
  const { exportVideo, exportPhotoVideo } = await import('../scene/export_video.js')
  const { exportPdb } = await import('../api/client.js')
  const { createPhotoMode } = await import('../scene/photo_mode.js')
  const stopNativeVR = vi.fn(), setState = vi.fn()
  const runtime = initScene(document.querySelector('canvas'), { placementStore: { setState }, stopNativeVR })
  runtime.scene.add(new Mesh(new BoxGeometry(), new MeshBasicMaterial()))
  const draw = runtime.renderer.render, frame = runtime.renderer.setAnimationLoop.mock.calls[0][0]
  const update = vi.fn(); runtime.addFrameCallback(update)
  frame()
  expect(draw).toHaveBeenCalledOnce(); expect(update).toHaveBeenCalledOnce()
  const endXR = vi.fn()
  runtime.renderer.xr.getSession.mockReturnValue({ end: endXR })
  if (clearThrows) runtime.renderer.clear.mockImplementation(() => { throw new Error('lost GL context') })
  const detail = { code: 'NATIVE_PLACEMENT_INTEGRITY', review_required: true, phase: 'persistent-review-status' }
  const laterUpdate = vi.fn(); runtime.addFrameCallback(laterUpdate)
  update.mockImplementationOnce(() => window.dispatchEvent(new CustomEvent('nadoc:placement-integrity-failure', { detail })))
  frame()
  await Promise.resolve(); await Promise.resolve()
  expect(runtime.scene.visible).toBe(false)
  runtime.scene.visible = true
  expect(runtime.scene.visible).toBe(false)
  expect(setState).toHaveBeenCalledWith({ placementIntegrityFailure: detail })
  expect(endXR).toHaveBeenCalledOnce(); expect(stopNativeVR).toHaveBeenCalledOnce()
  expect(runtime.renderer.setRenderTarget).toHaveBeenCalledWith(null)
  if (clearThrows) expect(detail.render_shutdown_errors.clear_xr_buffer).toMatch(/lost GL context/)
  frame()
  expect(draw).toHaveBeenCalledOnce(); expect(update).toHaveBeenCalledTimes(2)
  expect(laterUpdate).not.toHaveBeenCalled()
  expect(() => runtime.scene.add(new Mesh())).toThrow(/blocked/)
  expect(() => runtime.renderer.render(runtime.scene, runtime.camera)).toThrow(/blocked/)
  expect(() => runtime.renderer.setAnimationLoop(vi.fn())).toThrow(/blocked/)
  expect(() => runtime.renderNow()).toThrow(/blocked/)
  expect(() => assertPlacementExportSafe(runtime.scene)).toThrow(/blocked/)
  const player = { play: vi.fn() }
  await expect(exportVideo({ scene: runtime.scene, player })).rejects.toThrow(/blocked/)
  await expect(exportPhotoVideo({ player })).rejects.toThrow(/blocked/)
  const photo = createPhotoMode(runtime)
  expect(() => photo.beginFrameSession(10, 10)).toThrow(/blocked/)
  await expect(photo.renderToBlob(10, 10)).rejects.toThrow(/blocked/)
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
  await expect(exportPdb()).rejects.toThrow(/blocked/)
  expect(player.play).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled()
  // A new viewport in this page also starts blocked; disposing one runtime
  // cannot clear the placement latch or make its geometry exportable.
  runtime.dispose()
  const replacement = new Scene(), secondaryRenderer = {
    setAnimationLoop: vi.fn(), clear: vi.fn(), render: vi.fn(), xr: {},
  }
  const guard = installPlacementSceneGuard({ scene: replacement, renderer: secondaryRenderer })
  expect(guard.blocked()).toBe(true); expect(replacement.visible).toBe(false)
  expect(() => replacement.add(new Mesh())).toThrow(/blocked/)
  guard.dispose()
})
