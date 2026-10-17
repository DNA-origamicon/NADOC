import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initClusterGizmo } from './cluster_gizmo.js'
import { initNucleotideTransformTool } from './nucleotide_transform_tool.js'
import { createMockStore } from '../test-helpers/mock_store.js'

vi.mock('../api/client.js', () => ({ putNucleotideTransform: vi.fn(), putNucleotideTransforms: vi.fn() }))
import { putNucleotideTransform, putNucleotideTransforms } from '../api/client.js'

const dispose = []
afterEach(() => { for (const close of dispose.splice(0)) close(); vi.clearAllMocks() })
const stage = () => ({ scene: new THREE.Scene(), camera: new THREE.PerspectiveCamera(),
  canvas: document.createElement('canvas'), controls: { enabled: true } })

it('uses the real placement gizmo on the private layer and restores its raycaster', () => {
  const view = stage(), callbacks = vi.fn()
  const pose = { id: 'a', helix_ids: ['h'], pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, 0, 1] }
  const store = createMockStore({ currentDesign: { cluster_transforms: [pose], cluster_joints: [] } })
  const gizmo = initClusterGizmo(store, view.controls, () => {}, null, callbacks, null, { displayLayer: 31 })
  dispose.push(() => gizmo.detach())
  gizmo.attach('a', view.scene, view.camera, view.canvas)
  const helper = view.scene.children.find(node => node.controls)
  expect(helper.layers.isEnabled(31)).toBe(true)
  expect(helper.controls.getRaycaster().layers.isEnabled(31)).toBe(true)
  gizmo.setTransform([3, 2, 1], [0, 0, 0, 1])
  expect(callbacks).toHaveBeenCalled()
  expect(gizmo.getPendingTransform('a').translation).toEqual([3, 2, 1])
  const raycaster = helper.controls.getRaycaster()
  gizmo.detach()
  expect(raycaster.layers.mask).toBe(1)
  expect(view.scene.children).toHaveLength(0)
})

it('does not restore a raycaster now owned by another view', () => {
  const view = stage()
  const store = createMockStore({ currentDesign: { cluster_transforms: [{ id: 'a', helix_ids: [],
    pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, 0, 1] }], cluster_joints: [] } })
  const gizmo = initClusterGizmo(store, view.controls, null, null, null, null, { displayLayer: 31 })
  dispose.push(() => gizmo.detach())
  gizmo.attach('a', view.scene, view.camera, view.canvas)
  const ray = view.scene.children.find(node => node.controls).controls.getRaycaster()
  ray.layers.set(7)
  gizmo.detach()
  expect(ray.layers.mask).toBe(1 << 7)
  ray.layers.set(0)
})

it('reuses nucleotide drag bodies for fixed historical targets without live publication or UI writes', async () => {
  document.body.innerHTML = '<div id="mode-indicator">Other owner</div><div id="move-rotate-panel"></div>'
  const view = stage(), onChange = vi.fn(), onCancel = vi.fn()
  const targets = [{ helix_id: 'h', bp_index: 4, direction: 'FORWARD', copy: 1 }]
  const store = createMockStore({ selection: { items: [{ kind: 'base', key: 'other:1:REVERSE' }] } })
  const info = target => target.helix_id === 'h' ? { centroid: new THREE.Vector3(1, 2, 3) } : null
  const tool = initNucleotideTransformTool({ ...view, store, designRenderer: { residueTransformInfo: info },
    historySession: { targets, onChange, onCancel, displayLayer: 31 } })
  dispose.push(() => tool.detach(false))
  expect(tool.activate()).toBe(true)
  const helper = view.scene.children.find(node => node.controls), tc = helper.controls
  expect(helper.layers.isEnabled(31)).toBe(true)
  tc.dispatchEvent({ type: 'dragging-changed', value: true })
  tc.object.position.x += 2
  tc.dispatchEvent({ type: 'change' })
  tc.dispatchEvent({ type: 'dragging-changed', value: false })
  expect(onChange).toHaveBeenLastCalledWith([expect.objectContaining({ kind: 'base', helix_id: 'h',
    bp_index: 4, copy_k: 1, translation: [2, 0, 0], compose: true })])
  expect(await tool.confirm()).toMatchObject({ accepted: false, reason: 'owned_history' })
  expect(putNucleotideTransform).not.toHaveBeenCalled()
  expect(putNucleotideTransforms).not.toHaveBeenCalled()
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(onCancel).toHaveBeenCalledOnce()
  expect(document.getElementById('mode-indicator').textContent).toBe('Other owner')
  expect(tool.isActive()).toBe(true) // The owning controller decides when cancellation is safe.
})
