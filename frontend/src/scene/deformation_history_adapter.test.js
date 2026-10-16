import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import * as editor from './deformation_editor.js'
import * as api from '../api/client.js'
import { store } from '../state/store.js'

vi.mock('../api/client.js', () => ({ addDeformation: vi.fn(), updateDeformation: vi.fn(), deleteDeformation: vi.fn() }))
vi.mock('../ui/toast.js', () => ({ showPersistentToast: vi.fn(), dismissToast: vi.fn() }))
const params = { kind: 'bend', curvature_deg_per_bp: .123456789, direction_deg: 15 }
const operation = { id: 'native-op', type: 'bend', plane_a_bp: 0, plane_b_bp: 21, params,
  affected_helix_ids: ['h'], cluster_ids: [], targets: null, target_ranges: null }
let previous
function setup() {
  previous = store.getState()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ clearRect() {}, fillText() {}, fillRect() {} })
  const helix = { id: 'h', bp_start: 0, length_bp: 22,
    axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 7 } }
  const design = { id: 'prefix', helices: [helix], strands: [], deformations: [],
    cluster_transforms: [{ id: 'prefix-group', name: 'Prefix group', helix_ids: ['h'], domain_ids: [] }] }
  const live = { ...design, id: 'latest', cluster_transforms: [{ id: 'later-group', helix_ids: ['h'] }] }
  const liveAxes = { h: { start: [100, 0, 0], end: [100, 0, 7] } }
  store.setState({ currentDesign: live, currentHelixAxes: liveAxes, activeClusterId: 'later-group' })
  const scene = new THREE.Scene(), onExit = vi.fn(), onPlaneDragEnd = vi.fn()
  const controls = { enabled: true }
  const renderer = { beginDeformPreview: vi.fn(), endDeformPreview: vi.fn(), setToolOpacity: vi.fn() }
  const canvas = document.createElement('canvas')
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 })
  editor.initDeformationEditor(scene, new THREE.PerspectiveCamera(), canvas, controls, renderer, onExit, onPlaneDragEnd)
  const adapter = { design, helixAxes: { h: { start: [10, 0, 0], end: [10, 0, 7] } },
    onPreview: vi.fn(async () => true), onConfirm: vi.fn(async () => false), onCancel: vi.fn(async () => false) }
  return { adapter, live, liveAxes, scene, renderer, onExit, controls, onPlaneDragEnd }
}
afterEach(async () => {
  editor.exitTool(); await editor.waitForDeformationIdle()
  if (previous) store.setState(previous)
  previous = null; vi.restoreAllMocks(); vi.clearAllMocks()
})
const canonicalUntouched = f => {
  expect(store.getState().currentDesign).toBe(f.live)
  expect(store.getState().currentHelixAxes).toBe(f.liveAxes)
  expect(api.addDeformation).not.toHaveBeenCalled()
  expect(api.updateDeformation).not.toHaveBeenCalled()
  expect(api.deleteDeformation).not.toHaveBeenCalled()
}

it('uses the fixed prefix for planes and group defaults without dimming or changing the live design', () => {
  const f = setup()
  editor.startToolForHistory(operation, f.adapter)
  expect(editor.getDeformationPlaneFrame(7).center[0]).toBe(10)
  expect(editor.getDeformDefaultClusterIds()).toEqual([])
  expect(editor.getPlanes()).toEqual({ a: { bp: 0 }, b: { bp: 21 } })
  canonicalUntouched(f)
  expect(f.renderer.setToolOpacity).not.toHaveBeenCalled()
})

it('dispatches private previews with input-only patches and never native authoring APIs', async () => {
  const f = setup(); editor.startToolForHistory(operation, f.adapter)
  await editor.previewDeformation({ ...params, direction_deg: 90 })
  expect(f.adapter.onPreview).toHaveBeenCalledWith(expect.objectContaining({
    plane_a_bp: 0, plane_b_bp: 21, cluster_ids: [], params: { ...params, direction_deg: 90 },
  }))
  const sent = f.adapter.onPreview.mock.calls[0][0]
  for (const key of ['id', 'affected_helix_ids', 'targets', 'target_ranges', 'design', 'feature_id']) expect(sent).not.toHaveProperty(key)
  canonicalUntouched(f)
  expect(f.renderer.beginDeformPreview).not.toHaveBeenCalled()
})

it('plane drag emits only plane/group changes so it cannot overwrite newer popup parameters', async () => {
  const f = setup(); editor.startToolForHistory(operation, f.adapter)
  await editor.previewDeformation({ ...params, direction_deg: 90 })
  f.adapter.onPreview.mockClear()
  editor.repositionPlane('B', 14)
  await Promise.resolve()
  expect(f.adapter.onPreview).toHaveBeenCalledWith(expect.objectContaining({ plane_a_bp: 0, plane_b_bp: 14 }))
  expect(f.adapter.onPreview.mock.calls[0][0]).not.toHaveProperty('params')
  canonicalUntouched(f)
})

it('uses current chosen groups on Apply and retains the local editor when Apply refuses', async () => {
  const f = setup(); editor.startToolForHistory(operation, f.adapter)
  await editor.setDeformSessionClusterIds(['prefix-group'])
  await editor.confirmDeformation(params)
  expect(f.adapter.onConfirm).toHaveBeenCalledWith(expect.objectContaining({ cluster_ids: ['prefix-group'] }))
  expect(editor.getState()).toBe('BOTH')
  canonicalUntouched(f)
})

it('Escape requests private cancellation but cannot close an unresolved commit', async () => {
  const f = setup(); editor.startToolForHistory(operation, f.adapter)
  editor.handleEscape(); await Promise.resolve()
  expect(f.adapter.onCancel).toHaveBeenCalledOnce()
  expect(editor.getState()).toBe('BOTH')
  canonicalUntouched(f)
})

it('explicit local finish tears down only tool state without another cancellation or canonical write', () => {
  const f = setup(); editor.startToolForHistory(operation, f.adapter)
  editor.finishHistoryTool()
  expect(editor.getState()).toBe('IDLE')
  expect(f.adapter.onCancel).not.toHaveBeenCalled()
  expect(f.onExit).toHaveBeenCalledOnce()
  canonicalUntouched(f)
})

it('force document exit drops local history inputs without attempting a saved-param restore', async () => {
  const f = setup(); editor.startToolForHistory(operation, f.adapter)
  await editor.previewDeformation(params)
  editor.exitTool(); await editor.waitForDeformationIdle()
  expect(editor.getState()).toBe('IDLE')
  canonicalUntouched(f)
  expect(f.onExit).toHaveBeenCalledOnce()
  expect(editor.getDeformDefaultClusterIds()).toEqual(['later-group'])
})

it('assigns the private display layer to every plane descendant and its picking ray', () => {
  const f = setup(); f.adapter.displayLayer = 31
  const existing = new THREE.Object3D(); f.scene.add(existing)
  editor.startToolForHistory(operation, f.adapter)
  const privateObjects = f.scene.children.filter(child => child !== existing)
  expect(privateObjects.length).toBe(2)
  for (const root of privateObjects) root.traverse(child => expect(child.layers.isEnabled(31)).toBe(true))
  expect(existing.layers.mask).toBe(1)
  const pick = vi.spyOn(THREE.Raycaster.prototype, 'intersectObjects').mockImplementation(function () {
    expect(this.layers.isEnabled(31)).toBe(true); return []
  })
  editor.handlePointerDown({ button: 0, clientX: 10, clientY: 10 })
  expect(pick).toHaveBeenCalledOnce()
  editor.finishHistoryTool()
  expect(existing.layers.mask).toBe(1)
})

it('releases owned plane geometry, materials and label textures on local finish', () => {
  const f = setup(); editor.startToolForHistory(operation, f.adapter)
  const owned = new Set(), shared = new Set()
  for (const root of f.scene.children) root.traverse(child => {
    if (child.geometry) (child.isSprite ? shared : owned).add(child.geometry)
    for (const material of Array.isArray(child.material) ? child.material : [child.material]) {
      if (!material) continue
      owned.add(material); if (material.map) owned.add(material.map)
    }
  })
  const disposals = [...owned].map(value => vi.spyOn(value, 'dispose'))
  const sharedDisposals = [...shared].map(value => vi.spyOn(value, 'dispose'))
  editor.finishHistoryTool()
  for (const dispose of disposals) expect(dispose).toHaveBeenCalledOnce()
  expect(sharedDisposals.length).toBeGreaterThan(0)
  for (const dispose of sharedDisposals) expect(dispose).not.toHaveBeenCalled()
})

it('restores a preexisting hover layer so repeated history sessions leave no reserved-layer objects', () => {
  const f = setup()
  vi.spyOn(THREE.Raycaster.prototype, 'setFromCamera').mockImplementation(function () {
    this.ray.origin.set(100, -10, 3); this.ray.direction.set(0, 1, 0)
  })
  editor.startTool('bend'); editor.handlePointerMove({ clientX: 50, clientY: 50 })
  const hover = f.scene.children.find(child => child.geometry?.type === 'SphereGeometry')
  expect(hover).toBeDefined()
  editor.exitTool(); hover.layers.set(5)
  f.adapter.displayLayer = 31
  for (let iteration = 0; iteration < 2; iteration++) {
    editor.startToolForHistory(operation, f.adapter)
    editor.handlePointerMove({ clientX: 50, clientY: 50 })
    editor.finishHistoryTool()
    expect(hover.layers.mask).toBe(1 << 5)
    f.scene.traverse(object => expect(object.layers.mask & (1 << 31)).toBe(0))
  }
  canonicalUntouched(f)
})

it('finishing during a plane drag releases controls without a final preview or plane notification', () => {
  const f = setup(); editor.startToolForHistory(operation, f.adapter)
  vi.spyOn(THREE.Raycaster.prototype, 'intersectObjects').mockImplementation(objects => [{ object: objects[0] }])
  expect(editor.handlePointerDown({ button: 0, clientX: 50, clientY: 50 })).toBe(true)
  expect(f.controls.enabled).toBe(false)
  editor.finishHistoryTool()
  document.dispatchEvent(new Event('pointerup'))
  expect(f.controls.enabled).toBe(true)
  expect(f.adapter.onPreview).not.toHaveBeenCalled()
  expect(f.onPlaneDragEnd).not.toHaveBeenCalled()
  canonicalUntouched(f)
})
