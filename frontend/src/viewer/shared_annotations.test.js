import { it, expect, vi, afterEach } from 'vitest'
import * as THREE from 'three'
import { createAnnotationController } from '../scene/annotation_controller.js'
import { initAnnotationOverlay, captureSceneAnnotations } from '../scene/annotation_overlay.js'
import { prepareScene, loadPreparedScene, validateScene } from './prepared_scene.js'
import { decodeContainer } from './package_container.js'
import { mountSharedAnnotations } from './shared_annotations.js'
import { createLiveFrameCapture } from './live_frame_capture.js'
import { createClipApplier } from './trajectory_clip.js'
afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = '' })
const pose = { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' }
function fixture() {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(55, 1, .1, 1000)
  camera.position.set(0, 0, 20); camera.lookAt(0, 0, 0)
  const container = document.createElement('div'); document.body.append(container)
  const controller = createAnnotationController({ setTimer: () => 1, clearTimer() {} })
  controller.syncFromDesign({ id: 'part', annotations: [] })
  const entries = [{ pos: new THREE.Vector3(1, 2, 0), nuc: { strand_id: 's1' } }]
  const overlay = initAnnotationOverlay({ container, scene, getCamera: () => camera, controller, getEntries: () => entries, getViewport: () => ({ width: 800, height: 600 }) })
  const visible = controller.add({ text: '<b>Target</b>', icon: 'check', calloutType: 'rounded', color: '#58a6ff', manual: true, screenPos: { x: .2, y: .3 }, refs: [{ kind: 'strand', id: 's1' }] })
  controller.add({ text: 'private hidden text', visible: false })
  const capture = () => ({ scene, view: { annotations: captureSceneAnnotations(scene) } })
  return { scene, camera, container, controller, entries, overlay, visible, capture, dispose() { overlay.dispose(); controller.dispose() } }
}
it('shares visible text, styles and target geometry, excluding hidden text and editor refs', async () => {
  const f = fixture(), source = f.capture()
  expect(source.view.annotations).toHaveLength(1)
  expect(source.view.annotations[0]).not.toHaveProperty('refs')
  const buffer = prepareScene({ ...source, camera: pose }), data = decodeContainer(buffer)
  expect(JSON.stringify(data)).not.toContain('private hidden text')
  const guest = await loadPreparedScene(buffer), parent = document.createElement('div'); document.body.append(parent)
  const remove = vi.fn(), runtime = { camera: f.camera, addFrameCallback: vi.fn(), removeFrameCallback: remove }
  const overlay = mountSharedAnnotations({ current: guest, container: parent, runtime })
  overlay.update()
  const box = parent.querySelector('.nadoc-anno')
  expect(box.textContent).toBe('<b>Target</b>')
  expect(box.querySelector('b')).toBeNull()
  expect(box.querySelector('.nadoc-anno__icon svg')).not.toBeNull()
  expect(box.classList.contains('nadoc-anno--rounded')).toBe(true)
  expect(box.querySelector('.nadoc-anno__grip')).toBeNull()
  expect(overlay.getRecord(f.visible.id).hasAnchor).toBe(true)
  overlay.dispose(); expect(remove).toHaveBeenCalledOnce(); expect(parent.children).toHaveLength(0)
  guest.dispose(); f.dispose(); expect(captureSceneAnnotations(f.scene)).toEqual([])
})
it('anchors follow shared live frames and the guest camera, and off removes callouts and highlights', async () => {
  const f = fixture(), source = f.capture(), bytes = prepareScene({ ...source, camera: pose })
  const guest = await loadPreparedScene(bytes), parent = document.createElement('div'); document.body.append(parent)
  const overlay = mountSharedAnnotations({ current: guest, container: parent, runtime: { camera: f.camera } })
  overlay.update()
  const before = overlay.getRecord(f.visible.id).dot.getAttribute('cx')
  const capture = createLiveFrameCapture(decodeContainer(bytes), source)
  f.entries[0].pos.x = 5
  createClipApplier(guest).apply(capture.frame(f.capture()))
  overlay.update(); const moved = overlay.getRecord(f.visible.id).dot.getAttribute('cx')
  expect(moved).not.toBe(before)
  f.camera.position.x = -5; f.camera.lookAt(0, 0, 0); overlay.update()
  expect(overlay.getRecord(f.visible.id).dot.getAttribute('cx')).not.toBe(moved)
  f.controller.setEnabled(false)
  const off = decodeContainer(prepareScene({ ...f.capture(), camera: pose }))
  expect(off.view.annotations).toEqual([])
  expect(off.root.children).toHaveLength(0)
  f.controller.setEnabled(true); expect(f.capture().view.annotations).toHaveLength(1)
  overlay.dispose(); guest.dispose(); f.dispose()
})
it('rejects invalid style, text and target references before mounting the guest', () => {
  const f = fixture(), bytes = prepareScene({ ...f.capture(), camera: pose })
  for (const patch of [{ targets: ['missing'] }, { size: Infinity }, { text: 'x'.repeat(501) }, { icon: '<svg>' }, { color: 'url(example)' }, { refs: [] }]) {
    const data = decodeContainer(bytes); Object.assign(data.view.annotations[0], patch)
    expect(() => validateScene(data)).toThrow('Invalid shared annotations')
  }
  f.dispose()
})

it('auto-places guest callouts outside the rendered structure even when the host pinned them over it', async () => {
  const f = fixture()
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(120)
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(45)
  f.entries[0].pos.set(0, 0, 0)
  f.controller.update(f.visible.id, { manual: true, screenPos: { x: .48, y: .48 } })
  const structure = new THREE.Mesh(new THREE.SphereGeometry(4, 16, 12), new THREE.MeshBasicMaterial())
  f.scene.add(structure)
  const guest = await loadPreparedScene(prepareScene({ ...f.capture(), camera: pose }))
  const parent = document.createElement('div'); document.body.append(parent)
  const overlay = mountSharedAnnotations({ current: guest, container: parent, runtime: { camera: f.camera } })
  overlay.update()
  const rect = overlay.getRecord(f.visible.id).rect
  // The central occupied region must not contain any part of the label.
  expect(rect.x + rect.w < 320 || rect.x > 480 || rect.y + rect.h < 220 || rect.y > 380).toBe(true)
  expect(guest.data.view.annotations[0].manual).toBe(true) // package stays immutable
  f.camera.position.set(20, 0, 0); f.camera.lookAt(0, 0, 0); overlay.update()
  const rotated = overlay.getRecord(f.visible.id).rect
  expect(rotated.x + rotated.w < 320 || rotated.x > 480 || rotated.y + rotated.h < 220 || rotated.y > 380).toBe(true)
  overlay.dispose(); guest.dispose(); structure.geometry.dispose(); structure.material.dispose(); f.dispose()
})
