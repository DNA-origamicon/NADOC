import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initSlicePlane } from './slice_plane.js'
import { createSweepPreview } from './sweep_preview.js'
import { sweepMetadata } from '../test-helpers/sweep_preview.js'

afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = '' })
it('refuses hidden legacy Extrude click and Enter while its picker has a private owner', async () => {
  document.body.innerHTML = '<div id="extrude-panel" hidden><input id="slice-length" value="21"><select id="slice-unit"><option value="bp">bp</option></select><button id="slice-extrude-btn">Extrude</button><button id="slice-cancel-btn">Cancel</button></div>'
  const ctx = new Proxy({ measureText: () => ({ width: 8 }) }, { get: (target, key) => target[key] ?? (() => {}) })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx)
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(), canvas = document.createElement('canvas')
  const onExtrude = vi.fn(async () => {}), design = { helices: [] }
  const picker = initSlicePlane(scene, camera, canvas, { enableRotate: true }, { getDesign: () => design, onExtrude })
  const release = picker.usePrivateContext({ design, helixAxes: {}, displayLayer: 31 })
  try {
    picker.show('XY', 0, false, false, { latticeType: 'SQUARE', newBundle: true }); picker.setSelectedCells([[0, 0]])
    document.getElementById('slice-extrude-btn').click()
    document.getElementById('slice-length').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await Promise.resolve(); expect(onExtrude).not.toHaveBeenCalled()
    release()
    picker.show('XY', 0, false, false, { latticeType: 'SQUARE', newBundle: true }); picker.setSelectedCells([[0, 0]])
    document.getElementById('slice-extrude-btn').click(); await Promise.resolve(); await Promise.resolve()
    expect(onExtrude).toHaveBeenCalledOnce()
    expect(onExtrude.mock.lastCall[0]).toMatchObject({ cells: [[0, 0]], lengthBp: 21 })
  } finally { release(); picker.hide(); scene.clear() }
})
it('binds the real lattice picker to the prefix and releases only its own private context', () => {
  const ctx = new Proxy({ measureText: () => ({ width: 8 }) }, { get: (target, key) => target[key] ?? (() => {}) })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx)
  const canvas = document.createElement('canvas'), scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera()
  const live = vi.fn(() => ({ helices: [] })), axes = vi.fn(() => ({}))
  const picker = initSlicePlane(scene, camera, canvas, { enableRotate: true }, { getDesign: live, getHelixAxes: axes })
  const prefix = { lattice_type: 'SQUARE', helices: [{ id: 'prefix', label: 'Prefix', grid_pos: [0, 0], length_bp: 2,
    bp_start: 0, axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: .34 } }] }
  const original = structuredClone(prefix)
  const releaseOld = picker.usePrivateContext({ design: prefix, helixAxes: {}, displayLayer: 31 })
  expect(releaseOld.isCurrent()).toBe(true)
  picker.show('XY', 0, false, false, { latticeType: 'SQUARE', newBundle: true })
  expect(live).not.toHaveBeenCalled(); expect(axes).not.toHaveBeenCalled()
  const root = scene.children[0]
  root.traverse(node => expect(node.layers.isEnabled(31)).toBe(true))
  const releaseNew = picker.usePrivateContext({ design: prefix, helixAxes: {}, displayLayer: 31 })
  expect(releaseOld.isCurrent()).toBe(false)
  picker.show('XY', 0, true)
  releaseOld(); expect(root.visible).toBe(true)
  expect(prefix).toEqual(original)
  const newCamera = new THREE.OrthographicCamera(-10, 10, 10, -10)
  picker.setCamera(newCamera)
  expect(releaseNew.isCurrent()).toBe(false)
  picker.show('XY', 0, false, true)
  releaseNew(); expect(root.visible).toBe(true)
  expect(live).toHaveBeenCalled(); root.traverse(node => expect(node.layers.mask).toBe(1))
  picker.hide()
  const geometries = new Set(), materials = new Set()
  root.traverse(node => { if (node.geometry) geometries.add(node.geometry); if (node.material) materials.add(node.material) })
  geometries.forEach(g => g.dispose()); materials.forEach(m => { m.map?.dispose(); m.dispose() }); root.removeFromParent()
})

it('picks and drags real private Sweep handles without changing canonical masks or the shared raycaster', () => {
  const canvas = document.createElement('canvas'); document.body.append(canvas)
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600 })
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 4 / 3, .1, 1000)
  camera.position.z = 40; camera.layers.set(31); camera.updateMatrixWorld(true)
  const canonical = new THREE.Object3D(); scene.add(canonical)
  const mask = vi.fn(), moved = vi.fn(), selected = vi.fn(), orbit = { enabled: true }
  let preview, sharedRay = null, originalMask = null
  preview = createSweepPreview(scene, { canvas, getCamera: () => camera, getControls: () => orbit, setPreviewHelices: mask,
    onSelect: i => { selected(i); preview.select(i) }, onMove: moved })
  try {
    preview.setPrivateDisplayLayer(31)
    const data = sweepMetadata(); data.points_nm = data.path_nm = [[0, 0, 0], [0, 5, 0]]
    preview.update(data)
    const screen = point => { const p = point.clone().project(camera); return { clientX: (p.x + 1) * 400, clientY: (1 - p.y) * 300 } }
    const fire = (type, p, button = 0) => { const e = new MouseEvent(type, { ...p, button, bubbles: true, cancelable: true }); Object.defineProperty(e, 'pointerId', { value: 1 }); canvas.dispatchEvent(e) }
    fire('pointerdown', screen(new THREE.Vector3(0, 5, 0))); expect(selected).toHaveBeenLastCalledWith(1)
    scene.updateMatrixWorld(true)
    const helper = scene.getObjectByName('sweep-point-gizmo'), shared = helper.controls.getRaycaster()
    sharedRay = shared; originalMask = shared.layers.mask
    shared.layers.set(4); const prior = shared.layers.mask
    let handle; helper.traverse(node => { if (!handle && node.name === 'X' && node.isMesh && node.visible) handle = node })
    handle.geometry.computeBoundingBox()
    const start = screen(handle.geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(handle.matrixWorld))
    fire('pointerdown', start); expect(orbit.enabled).toBe(false)
    fire('pointermove', { clientX: start.clientX + 40, clientY: start.clientY }, -1)
    fire('pointerup', start); expect(moved).toHaveBeenCalled(); expect(orbit.enabled).toBe(true)
    expect(shared.layers.mask).toBe(prior)
    for (const child of scene.children.filter(node => node !== canonical)) child.traverse(node => expect(node.layers.isEnabled(31)).toBe(true))
    expect(canonical.visible).toBe(true); expect(canonical.layers.mask).toBe(1); expect(mask).not.toHaveBeenCalled()
    preview.setPrivateDisplayLayer(null); expect(mask).not.toHaveBeenCalled()
  } finally { if (sharedRay) sharedRay.layers.mask = originalMask; preview.dispose() }
  expect(scene.children).toEqual([canonical])
})
