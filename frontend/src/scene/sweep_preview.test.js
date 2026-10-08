import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { createSweepPreview } from './sweep_preview.js'

it('raycasts points, translates the selected point in its saved frame, and cleans up controls', () => {
  const canvas = document.createElement('canvas')
  document.body.append(canvas)
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600 })
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 800 / 600, .1, 1000)
  camera.position.set(0, 0, 40); camera.updateMatrixWorld(true)
  const orbit = { enabled: true }, moved = vi.fn(), selected = vi.fn()
  let preview
  preview = createSweepPreview(scene, { canvas, getCamera: () => camera, getControls: () => orbit,
    onSelect: index => { selected(index); preview.select(index) }, onMove: moved })
  preview.update({ origin_nm: [0,0,0], point_rotation: [[0,-1,0],[1,0,0],[0,0,1]],
    points_nm: [[0,0,0],[0,5,0]], path_nm: [[0,0,0],[0,5,0]], helix_paths_nm: [[[0,0,0],[0,5,0]]] })
  const screen = p => { const v = p.clone().project(camera); return { x: (v.x + 1) * 400, y: (1 - v.y) * 300 } }
  const fire = (type, p, button = 0) => { const event = new MouseEvent(type, { clientX: p.x, clientY: p.y, button, bubbles: true, cancelable: true }); Object.defineProperty(event, 'pointerId', { value: 1 }); canvas.dispatchEvent(event) }
  fire('pointerdown', screen(new THREE.Vector3(0,0,0)))
  expect(selected).toHaveBeenLastCalledWith(0)
  expect(scene.getObjectByName('sweep-point-gizmo').visible).toBe(false)
  fire('pointerdown', screen(new THREE.Vector3(0,5,0)))
  expect(selected).toHaveBeenLastCalledWith(1)
  scene.updateMatrixWorld(true)
  const helper = scene.getObjectByName('sweep-point-gizmo')
  const handles = []
  helper.traverse(o => { if (o.name === 'X' && o.isMesh && o.visible) handles.push(o) })
  const handle = handles[0]
  handle.geometry.computeBoundingBox()
  const center = handle.geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(handle.matrixWorld)
  const start = screen(center)
  fire('pointerdown', start)
  expect(orbit.enabled).toBe(false)
  fire('pointermove', { x: start.x + 40, y: start.y }, -1)
  fire('pointerup', { x: start.x + 40, y: start.y })
  expect(orbit.enabled).toBe(true)
  expect(moved).toHaveBeenCalled()
  const [index, point] = moved.mock.lastCall
  expect(index).toBe(1)
  expect(point[0]).toBeCloseTo(5, 2)
  expect(point[1]).toBeLessThan(-1)
  preview.clear()
  expect(scene.getObjectByName('sweep-control-points').children).toHaveLength(0)
  expect(helper.visible).toBe(false)
  preview.dispose(); canvas.remove()
  expect(scene.children).toHaveLength(0)
})

it('previews a single-base continuation without invalid tube vertices', () => {
  const scene = new THREE.Scene(), preview = createSweepPreview(scene)
  preview.update({ points_nm: [[0,0,0],[0,0,.1]], path_nm: [[0,0,0],[0,0,.1]], helix_paths_nm: [[[0,0,.1],[0,0,.1]]] })
  scene.traverse(o => { if (o.geometry) expect([...o.geometry.attributes.position.array].every(Number.isFinite)).toBe(true) })
  preview.setPoints([[0,0,0]], 0)
  expect(scene.getObjectByName('sweep-control-points').children).toHaveLength(1)
  preview.dispose()
})
