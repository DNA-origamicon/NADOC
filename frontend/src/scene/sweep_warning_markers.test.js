import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { warningSegmentCenters, initSavedSweepWarnings, SWEEP_LIMIT_TEXT } from './sweep_warning_markers.js'

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
