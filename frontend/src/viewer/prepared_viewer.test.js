import { it, expect, vi, afterEach } from 'vitest'
import * as THREE from 'three'
vi.mock('../perf/viewer_performance.js', () => ({ initViewerPerformance: () => ({ busy: false, stop: vi.fn(), dispose: vi.fn() }) }))
vi.mock('./runtime.js', () => ({ initScene: vi.fn() }))
vi.mock('./prepared_scene.js', () => ({ loadPreparedScene: vi.fn() }))
import { initScene } from './runtime.js'
import { loadPreparedScene } from './prepared_scene.js'
import { mountPreparedViewer } from './prepared_viewer.js'
afterEach(() => { vi.clearAllMocks(); document.body.innerHTML = '' })
function setup() {
  document.body.innerHTML = '<main><canvas></canvas></main><h1></h1><p></p><input type="file"><button></button><select></select>'
  const runtime = { scene: new THREE.Scene(), camera: new THREE.PerspectiveCamera(), controls: { target: new THREE.Vector3(), update: vi.fn() },
    renderer: { setClearColor: vi.fn() }, switchOrbitMode: vi.fn(), setNavScaleProvider: vi.fn(), dispose: vi.fn() }
  initScene.mockReturnValue(runtime)
  const viewer = mountPreparedViewer({ canvas: document.querySelector('canvas'), status: document.querySelector('p'), title: document.querySelector('h1'), fileInput: document.querySelector('input'), resetButton: document.querySelector('button'), modeInput: document.querySelector('select') })
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
