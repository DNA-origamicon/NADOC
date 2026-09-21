import * as THREE from 'three'
import { afterEach, expect, it, vi } from 'vitest'
import { getViewerPerformance, initViewerPerformance } from './viewer_performance.js'

afterEach(() => { getViewerPerformance()?.dispose(); vi.useRealTimers() })

function fixture(options = {}) {
  const canvas = document.createElement('canvas')
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000)
  camera.position.set(10, 5, 10)
  const controls = { target: new THREE.Vector3(), enabled: true, update: vi.fn() }
  let state = { currentDesign: { id: 'a', helices: [] }, currentAssembly: null,
    atomisticMode: 'off', surfaceMode: 'off', coloringMode: 'strand' }
  const callbacks = new Set()
  const api = initViewerPerformance({
    renderer: { domElement: canvas, xr: {}, getPixelRatio: () => 1, getContext: () => ({ getExtension: () => null }),
      info: { render: { calls: 5, triangles: 100 }, memory: { geometries: 3, textures: 0 } } },
    camera, controls, store: { getState: () => state },
    captureCurrentCamera: () => ({ position: camera.position.toArray(), up: camera.up.toArray(), target: controls.target.toArray() }),
    ...options,
    addFrameCallback: fn => callbacks.add(fn), removeFrameCallback: fn => callbacks.delete(fn),
  })
  return { api, camera, controls, callbacks, canvas, change: () => { state = { ...state, currentDesign: { id: 'b' } } } }
}

it('leaves no per-frame callback when idle and restores controls on context loss', async () => {
  const { api, camera, controls, callbacks, canvas } = fixture()
  const position = camera.position.clone()
  expect(callbacks.size).toBe(0)
  await api.start()
  expect(controls.enabled).toBe(false)
  expect(callbacks.size).toBe(1)
  canvas.dispatchEvent(new Event('webglcontextlost'))
  expect(api.latest).toMatchObject({ valid: false, invalid_reason: 'WebGL context lost' })
  expect(controls.enabled).toBe(true)
  expect(camera.position.equals(position)).toBe(true)
  expect(callbacks.size).toBe(0)
})

it('invalidates a changed fixture and does not leave controls disabled on disposal', async () => {
  const { api, change, controls, callbacks } = fixture()
  await api.start()
  change()
  for (const frame of [...callbacks]) frame()
  expect(api.latest.invalid_reason).toBe('Design or assembly changed')
  expect(controls.enabled).toBe(true)
  await api.start()
  api.dispose()
  expect(controls.enabled).toBe(true)
  expect(callbacks.size).toBe(0)
})

it('records stalled render loops as invalid rather than successful short runs', async () => {
  vi.useFakeTimers()
  const { api } = fixture()
  await api.start({ durationMs: 1000 })
  vi.advanceTimersByTime(6000)
  expect(api.latest).toMatchObject({ valid: false, invalid_reason: 'Capture timed out; render loop may have stalled' })
})

it('repeats the benchmark pose but restores the user viewpoint on stop', async () => {
  const { api, camera } = fixture()
  const first = camera.position.clone()
  await api.start()
  api.stop()
  camera.position.set(100, 20, 30)
  const userPosition = camera.position.clone()
  await api.start()
  expect(camera.position.equals(first)).toBe(true)
  api.stop()
  expect(camera.position.equals(userPosition)).toBe(true)
})

it('labels a prepared package with both source identity and actual package identity', async () => {
  const { api } = fixture({ getFixtureIdentity: () => ({ sha256: 'a'.repeat(64), kind: 'JSON design/assembly document; not simulation content', package_sha256: 'b'.repeat(64) }) })
  await api.start(); api.stop()
  expect(api.latest).toMatchObject({ fixture_sha256: 'a'.repeat(64), package_sha256: 'b'.repeat(64), viewer_kind: 'prepared-static-snapshot' })
})
