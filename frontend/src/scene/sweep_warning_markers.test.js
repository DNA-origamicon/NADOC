import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { warningSegmentCenters, createSweepWarningMarkers, initSavedSweepWarnings, SWEEP_LIMIT_TEXT } from './sweep_warning_markers.js'

it('coalesces adjacent warning segments while preserving separate bend regions', () => {
  const path = Array.from({ length: 8 }, (_, i) => [i, 0, 0])
  expect(warningSegmentCenters(path, [5, 1, 2, 1, 6, 8])).toEqual([[1.5, 0, 0], [5.5, 0, 0]])
})

it('keeps saved warnings on live geometry, raycasts hover, and removes them on undo', () => {
  const canvas = document.createElement('canvas')
  document.body.append(canvas)
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600 })
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 4/3, .1, 1000)
  camera.position.z = 40; camera.updateMatrixWorld(true)
  const currentDesign = { deformations: [{ type: 'sweep', affected_helix_ids: ['h'], params: { warning_bps: [5] } }] }
  let state = { currentDesign, currentGeometry: [{ helix_id: 'h', bp_index: 6, direction: 1, backbone_position: [0, 0, 0] }] }
  let changed, frame
  const unsubscribe = vi.fn(), removeFrameCallback = vi.fn()
  const pos = new THREE.Vector3()
  const warnings = initSavedSweepWarnings(scene, {
    getState: () => state, subscribe: callback => { changed = callback; return unsubscribe },
  }, { canvas, getCamera: () => camera,
    getHelixCtrl: () => ({ lookupEntry: key => key === 'h:6:1' ? { pos } : undefined }),
    addFrameCallback: callback => { frame = callback }, removeFrameCallback,
  })
  const group = scene.getObjectByName('sweep-warning-icons-saved')
  expect(group.children).toHaveLength(1)
  const hover = (x, y) => canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: x, clientY: y, bubbles: true }))
  hover(400, 300)
  const tooltip = document.querySelector('[role="tooltip"]')
  expect(tooltip.textContent).toBe(SWEEP_LIMIT_TEXT)
  expect(tooltip.style.display).toBe('block')
  hover(20, 20)
  expect(tooltip.style.display).toBe('none')
  pos.set(5, 2, 0); frame()
  expect(group.children[0].position.toArray()).toEqual([5, 2, 0])
  hover(400, 300)
  expect(tooltip.style.display).toBe('none')
  const old = state
  state = { currentDesign: { deformations: [] }, currentGeometry: [] }; changed(state, old)
  expect(group.children).toHaveLength(0)
  warnings.dispose(); canvas.remove()
  expect(unsubscribe).toHaveBeenCalled()
  expect(removeFrameCallback).toHaveBeenCalledWith(frame)
  expect(scene.children).toHaveLength(0)
  expect(document.querySelector('[role="tooltip"]')).toBeNull()
})

it('does no layout, camera or controller work while the marker overlay is empty, hidden or disposed', () => {
  const scene = new THREE.Scene(), canvas = document.createElement('canvas')
  const camera = new THREE.PerspectiveCamera(45, 1, .1, 1000); camera.position.z = 40
  const bounds = vi.fn(() => ({ height: 600 })), getCamera = vi.fn(() => camera), getHelixCtrl = vi.fn()
  canvas.getBoundingClientRect = bounds
  let frame
  const markers = createSweepWarningMarkers(scene, { canvas, getCamera, getHelixCtrl,
    addFrameCallback: callback => { frame = callback }, removeFrameCallback: vi.fn() })
  const group = scene.getObjectByName('sweep-warning-icons-preview')
  markers.set([]); frame(); frame()
  expect(bounds).not.toHaveBeenCalled()
  expect(getCamera).not.toHaveBeenCalled()
  expect(getHelixCtrl).not.toHaveBeenCalled()
  markers.set([[0, 0, 0]])
  expect(bounds).toHaveBeenCalledOnce()
  group.visible = false; frame()
  expect(bounds).toHaveBeenCalledOnce()
  group.visible = true; frame()
  expect(bounds).toHaveBeenCalledTimes(2)
  markers.set([]); frame()
  expect(bounds).toHaveBeenCalledTimes(2)
  markers.set([[0, 0, 0]])
  markers.dispose(); frame(); markers.set([[1, 2, 3]])
  expect(bounds).toHaveBeenCalledTimes(3)
  expect(scene.children).toHaveLength(0)
})

it('avoids traversing geometry without saved sweep warnings and rebuilds when warnings appear', () => {
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera()
  let state = { currentDesign: { deformations: [{ type: 'sweep', params: { warning_bps: [] } }] },
    currentGeometry: { [Symbol.iterator]: vi.fn(() => { throw new Error('unused geometry scan') }) } }
  let changed
  const markers = initSavedSweepWarnings(scene, {
    getState: () => state, subscribe: callback => { changed = callback; return vi.fn() },
  }, { getCamera: () => camera })
  expect(state.currentGeometry[Symbol.iterator]).not.toHaveBeenCalled()
  const old = state
  state = { currentDesign: { deformations: [{ type: 'sweep', affected_helix_ids: ['h'], params: { warning_bps: [5] } }] },
    currentGeometry: [
      { helix_id: 'h', bp_index: 4, direction: 1, backbone_position: [1, 2, 3] },
      { helix_id: 'h', bp_index: 6, direction: -1, backbone_position: [3, 4, 5] },
      { helix_id: 'other', get bp_index() { throw new Error('unaffected helix') } },
    ] }
  changed(state, old)
  const group = scene.getObjectByName('sweep-warning-icons-saved')
  expect(group.children).toHaveLength(1)
  expect(group.children[0].position.toArray()).toEqual([2, 3, 4])
  const previous = state
  state = { ...state, currentGeometry: [{ helix_id: 'h', bp_index: 5, direction: 1, backbone_position: [8, 9, 10] }] }
  changed(state, previous)
  expect(group.children[0].position.toArray()).toEqual([8, 9, 10])
  markers.dispose()
})

it('keeps visible marker positions, camera orientation and screen scale live across frames', () => {
  const scene = new THREE.Scene(), canvas = document.createElement('canvas')
  let height = 600, position = new THREE.Vector3(1, 2, 3), frame
  canvas.getBoundingClientRect = () => ({ height })
  const camera = new THREE.PerspectiveCamera(45, 1, .1, 1000); camera.position.z = 40
  const markers = createSweepWarningMarkers(scene, { canvas, getCamera: () => camera,
    getHelixCtrl: () => ({ lookupEntry: () => ({ pos: position }) }),
    addFrameCallback: callback => { frame = callback }, removeFrameCallback: vi.fn() })
  markers.set([{ position: [0, 0, 0], keys: ['h:1:FORWARD'] }])
  const icon = scene.getObjectByName('sweep-warning-icons-preview').children[0]
  const initialScale = icon.scale.x
  height = 1200; camera.rotation.y = .5; frame()
  expect(icon.scale.x).toBe(initialScale / 2)
  expect(icon.quaternion.toArray()).toEqual(camera.quaternion.toArray())
  position = new THREE.Vector3(4, 5, 6); frame()
  expect(icon.position.toArray()).toEqual([4, 5, 6])
  markers.dispose()
})
