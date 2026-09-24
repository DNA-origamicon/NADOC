import { it, expect, vi, afterEach } from 'vitest'
import * as THREE from 'three'
vi.mock('../perf/viewer_performance.js', () => ({ initViewerPerformance: () => ({ busy: false, stop: vi.fn(), dispose: vi.fn() }) }))
vi.mock('./runtime.js', () => ({ initScene: vi.fn() }))
vi.mock('./prepared_scene.js', () => ({ loadPreparedScene: vi.fn() }))
import { initScene } from './runtime.js'
import { loadPreparedScene } from './prepared_scene.js'
import { mountPreparedViewer } from './prepared_viewer.js'
afterEach(() => { vi.clearAllMocks(); document.body.innerHTML = '' })
function setup(mobile = false) {
  document.body.innerHTML = '<main><canvas></canvas></main><h1></h1><p></p><input type="file"><button></button><select></select>'
  const runtime = { scene: new THREE.Scene(), camera: new THREE.PerspectiveCamera(), controls: { target: new THREE.Vector3(), update: vi.fn() },
    resetRenderFn: vi.fn(), setRenderFn: vi.fn(), renderer: { setClearColor: vi.fn() }, switchOrbitMode: vi.fn(), setNavScaleProvider: vi.fn(), dispose: vi.fn() }
  initScene.mockReturnValue(runtime)
  const viewer = mountPreparedViewer({ mobile, canvas: document.querySelector('canvas'), status: document.querySelector('p'), title: document.querySelector('h1'), fileInput: document.querySelector('input'), resetButton: document.querySelector('button'), modeInput: document.querySelector('select') })
  return { viewer, runtime }
}
const file = { name: 'part.nadocview', size: 10, arrayBuffer: async () => new ArrayBuffer(10) }
const scene = () => ({ scene: new THREE.Scene(), dispose: vi.fn(), data: { camera: { position: [1, 2, 3], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' }, title: '<script>bad()</script>', render: { clearColor: 0, clearAlpha: 0 }, background: '#161b22', navigation: new Float64Array() } })
it('preserves the last valid scene after an invalid file and disposes resources exactly once', async () => {
  const { viewer, runtime } = setup(), first = scene()
  loadPreparedScene.mockResolvedValueOnce(first)
  await viewer.loadFile(file)
  expect(document.querySelector('h1').textContent).toBe(first.data.title)
  expect(document.querySelector('script')).toBeNull()
  loadPreparedScene.mockRejectedValueOnce(new Error('Unsupported version'))
  await viewer.loadFile(file)
  expect(viewer.current).toBe(first)
  expect(document.querySelector('p').textContent).toContain('Unsupported version')
  viewer.dispose(); viewer.dispose()
  expect(first.dispose).toHaveBeenCalledTimes(1)
  expect(runtime.dispose).toHaveBeenCalledTimes(1)
})
it('drops a stale async load without replacing the newest scene or leaking it', async () => {
  const { viewer } = setup(), older = scene(), newer = scene()
  let finish
  loadPreparedScene.mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockResolvedValueOnce(newer)
  const pending = viewer.loadFile(file)
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  await viewer.loadFile(file)
  finish(older); await pending
  expect(viewer.current).toBe(newer)
  expect(older.dispose).toHaveBeenCalledTimes(1)
  viewer.dispose()
})
it('applies a shared perspective without changing the snapshot reset pose', async () => {
  const { viewer, runtime } = setup(), loaded = scene(); loadPreparedScene.mockResolvedValueOnce(loaded)
  await viewer.loadFile(file)
  const camera = { position: [30, 40, 50], target: [1, 0, 0], up: [0, 0, 1], fov: 70, near: .2, far: 4000, orbitMode: 'trackball' }
  viewer.applyCamera(camera)
  expect(runtime.camera.position.toArray()).toEqual(camera.position)
  expect(runtime.controls.target.toArray()).toEqual(camera.target)
  expect(runtime.camera.fov).toBe(70); expect(runtime.switchOrbitMode).toHaveBeenLastCalledWith('trackball')
  document.querySelector('button').click()
  expect(runtime.camera.position.toArray()).toEqual(loaded.data.camera.position)
  expect(loaded.data.camera.fov).toBe(55); viewer.dispose()
})

it('preserves the guest camera and checks revision identity before replacing the scene', async () => {
  const { viewer, runtime } = setup(), first = scene(), next = scene(), wrong = scene()
  loadPreparedScene.mockResolvedValueOnce(first); await viewer.loadFile(file)
  const pose = { ...first.data.camera, position: [40, 50, 60], near: .3, far: 3000 }
  runtime.captureCurrentCamera = () => pose
  next.packageHash = 'correct'; next.data.render.localClippingEnabled = true
  loadPreparedScene.mockResolvedValueOnce(next)
  await viewer.loadFile(file, { preserveCamera: true, expectedHash: 'correct' })
  expect(runtime.camera.position.toArray()).toEqual(pose.position)
  expect(runtime.renderer.localClippingEnabled).toBe(true)
  wrong.packageHash = 'wrong'; loadPreparedScene.mockResolvedValueOnce(wrong)
  expect(await viewer.loadFile(file, { expectedHash: 'correct' })).toBe(false)
  expect(viewer.current).toBe(next); expect(wrong.dispose).toHaveBeenCalledOnce(); viewer.dispose()
})

it('updates and removes host view-tool legends with scene replacement and meeting cleanup', async () => {
  const { viewer } = setup(), first = scene(), next = scene()
  first.data.view = { viewTools: { lengthHeatmap: true, clashes: true, clashCount: 3 } }
  loadPreparedScene.mockResolvedValueOnce(first); await viewer.loadFile(file)
  expect(document.querySelector('.shared-length-legend')).not.toBeNull()
  expect(document.querySelector('.shared-clash-legend').textContent).toBe('3 clashes')
  loadPreparedScene.mockResolvedValueOnce(next); await viewer.loadFile(file)
  expect(document.querySelector('.shared-view-tools').hidden).toBe(true)
  loadPreparedScene.mockResolvedValueOnce(first); await viewer.loadFile(file)
  viewer.clear(); expect(document.querySelector('.shared-view-tools').hidden).toBe(true)
  viewer.dispose(); expect(document.querySelector('.shared-view-tools')).toBeNull()
})

it('installs the overlay renderer and restores normal rendering on replacement and clear', async () => {
  const { viewer, runtime } = setup(), overlay = scene(), native = scene()
  overlay.data.view = { overlay: ['one', 'two'] }
  loadPreparedScene.mockResolvedValueOnce(overlay).mockResolvedValueOnce(native)
  await viewer.loadFile(file)
  expect(runtime.setRenderFn).toHaveBeenCalledOnce()
  await viewer.loadFile(file)
  expect(runtime.resetRenderFn).toHaveBeenCalledTimes(2)
  viewer.clear()
  expect(runtime.resetRenderFn).toHaveBeenCalledTimes(3)
  viewer.dispose()
})

it('keeps Orbit on mobile when a desktop presenter uses Multiscale or Trackball', async () => {
  const { viewer, runtime } = setup(true), next = scene()
  next.data.camera.orbitMode = 'multiscale'
  loadPreparedScene.mockResolvedValueOnce(next); await viewer.loadFile(file)
  expect(initScene).toHaveBeenLastCalledWith(document.querySelector('canvas'), { pixelRatioCap: 1, pauseWhenHidden: true })
  expect(runtime.switchOrbitMode).toHaveBeenLastCalledWith('orbit')
  viewer.applyCamera({ ...next.data.camera, orbitMode: 'trackball' })
  expect(runtime.switchOrbitMode).toHaveBeenLastCalledWith('orbit')
  viewer.dispose()
})
