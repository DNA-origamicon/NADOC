import { it, expect, vi, afterEach } from 'vitest'
vi.mock('./prepared_scene.js', () => ({ prepareScene: vi.fn(() => new ArrayBuffer(16)) }))
import { prepareScene } from './prepared_scene.js'
import { initPreparedExport } from './export_prepared.js'
afterEach(() => vi.clearAllMocks())
it('exports display geometry and navigation without writes or editor history', async () => {
  const state = { currentDesign: { metadata: { name: 'Part' }, helices: [], feature_history: ['private'] } }
  const store = { getState: () => state }, scene = {}, camera = { near: .1, far: 2000 }
  const api = initPreparedExport({ scene, camera, store, renderer: {}, captureCurrentCamera: () => ({ fov: 55 }), document: { getElementById: () => null } })
  const result = await api.exportView()
  expect(result.title).toBe('Part')
  const spec = prepareScene.mock.calls[0][0]
  expect(spec.scene).toBe(scene)
  expect(spec.camera.near).toBe(.1)
  expect(spec.navigation).toBeInstanceOf(Float64Array)
  expect(spec).not.toHaveProperty('design')
  expect(state.currentDesign.feature_history).toEqual(['private'])
  state.cadnanoActive = true
  await expect(api.exportView()).rejects.toThrow('3D view')
  api.dispose()
})

it('rejects render overrides instead of silently omitting photo or alternate-camera effects', async () => {
  const api = initPreparedExport({ scene: {}, camera: {}, store: { getState: () => ({ currentDesign: {} }) }, isStandardRender: () => false, document: { getElementById: () => null } })
  await expect(api.exportView()).rejects.toThrow('normal 3D view')
  expect(prepareScene).not.toHaveBeenCalled()
})
