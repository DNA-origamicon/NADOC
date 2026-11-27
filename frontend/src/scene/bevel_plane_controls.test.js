// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createBevelPlaneControls } from './bevel_plane_controls.js'
import { bevelPlane } from './bevel_math.js'
it('drags the plane face by real raycast, restores orbit on cancel, and reserves Tab only outside fields', () => {
  const canvas = document.createElement('canvas'); document.body.append(canvas)
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 1000 })
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(50, 1, .1, 1000)
  camera.position.set(25, 20, 25); camera.lookAt(0, 0, 10); camera.updateMatrixWorld()
  const paths = [{ helix_id: 'h', bps: [0, 10, 20], points: [[0, 0, 0], [0, 0, 10], [0, 0, 20]],
    tangents: [[0, 0, 1], [0, 0, 1], [0, 0, 1]], rights: [[1, 0, 0], [1, 0, 0], [1, 0, 0]] }]
  const values = { positionBp: 10, angleDeg: 0, directionDeg: 0, trimEnd: 'end' }, controls = { enabled: true }, onChange = vi.fn()
  const plane = createBevelPlaneControls({ scene, camera, canvas, controls, onChange })
  plane.update(bevelPlane(paths, values), paths, values)
  const event = (name, z) => { const p = new THREE.Vector3(0, 0, z).project(camera)
    canvas.dispatchEvent(new MouseEvent(name, { clientX: (p.x + 1) * 500, clientY: (1 - p.y) * 500, button: 0, bubbles: true })) }
  event('pointerdown', 10); expect(controls.enabled).toBe(false)
  event('pointermove', 15); expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ positionBp: expect.any(Number) }))
  expect(onChange.mock.calls[0][0].positionBp).not.toBe(10)
  event('pointercancel', 15); expect(controls.enabled).toBe(true)
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
  expect(scene.getObjectByName('bevel-plane-controls').userData.mode).toBe('rotate')
  const field = document.createElement('input'); document.body.append(field)
  field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
  expect(scene.getObjectByName('bevel-plane-controls').userData.mode).toBe('rotate')
  plane.dispose(); expect(scene.children).toHaveLength(0); document.body.replaceChildren()
})
