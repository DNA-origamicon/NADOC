import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { initSlicePlane } from './slice_plane.js'

it('toggles mouse box selection with Tab, not in fields, and cleans up cancelled drags', () => {
  const context = new Proxy({ measureText: () => ({ width: 20 }) }, {
    get: (target, key) => target[key] ?? (() => {}),
  })
  const spy = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
  const canvas = document.createElement('canvas')
  document.body.appendChild(canvas)
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600 })
  canvas.setPointerCapture = vi.fn()
  canvas.hasPointerCapture = () => true
  canvas.releasePointerCapture = vi.fn()
  const scene = new THREE.Scene()
  const camera = new THREE.OrthographicCamera(-100, 100, 75, -75, .1, 1000)
  camera.position.z = 100
  camera.updateMatrixWorld()
  const sp = initSlicePlane(scene, camera, canvas, { enabled: true }, { getDesign: () => null })
  const tab = target => {
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    target.dispatchEvent(event)
    return event.defaultPrevented
  }
  const pointer = (type, x, y, pointerType = 'mouse') => {
    const event = new MouseEvent(type, { clientX: x, clientY: y, button: 0, bubbles: true })
    Object.defineProperties(event, { pointerId: { value: 1 }, pointerType: { value: pointerType } })
    canvas.dispatchEvent(event)
  }
  try {
    expect(tab(document.body)).toBe(false)
    sp.show('XY', 0, false, false, { newBundle: true })
    scene.updateMatrixWorld(true)
    const field = document.createElement('input')
    document.body.appendChild(field)
    expect(tab(field)).toBe(false)
    field.remove()
    expect(tab(document.body)).toBe(true)
    const fills = []
    scene.traverse(object => {
      if (object.geometry?.type === 'CircleGeometry') fills.push(object)
    })
    const sample = fills[0]
    const originalColor = sample.material.color.clone()
    pointer('pointerdown', 10, 10)
    pointer('pointermove', 790, 590)
    // The box reaches far beyond the normal cursor halo, but all candidates
    // are visible and tinted without committing selection or numbering.
    expect(sp.getSelectedCells()).toHaveLength(0)
    expect(sample.material.opacity).toBe(0.65)
    expect(sample.material.color.equals(originalColor)).toBe(false)
    const previewColor = sample.material.color.clone()
    const projected = sample.getWorldPosition(new THREE.Vector3()).project(camera)
    const sampleX = (projected.x + 1) * 400
    // A partially enclosed cell is bright within the expanded halo, but has
    // no candidate tint until the rightward window fully encloses it.
    pointer('pointermove', sampleX, 590)
    expect(sample.material.color.equals(originalColor)).toBe(true)
    expect(sample.material.opacity).toBe(0.55)
    pointer('pointermove', 20, 20)
    expect(sample.material.color.equals(originalColor)).toBe(true)
    expect(sample.material.opacity).toBeLessThan(0.1)
    pointer('pointermove', 790, 590)
    pointer('pointercancel', 790, 590)
    expect(sp.getSelectedCells()).toHaveLength(0)
    expect(sample.material.color.equals(originalColor)).toBe(true)
    expect(sample.material.opacity).toBeLessThan(0.1)
    pointer('pointerdown', 10, 10)
    pointer('pointermove', 790, 590)
    pointer('pointerup', 790, 590)
    expect(sample.material.color.equals(previewColor)).toBe(false)
    expect(sample.material.opacity).toBe(0.9)
    expect(sp.getSelectedCells().length).toBeGreaterThan(0)
    expect(canvas.releasePointerCapture).toHaveBeenCalledWith(1)
    const count = sp.getSelectedCells().length
    pointer('pointerdown', 10, 10)
    pointer('pointermove', 790, 590)
    pointer('pointercancel', 790, 590)
    expect(sp.getSelectedCells()).toHaveLength(count)
    expect(document.body.textContent).toContain('Box select')
    expect(tab(document.body)).toBe(true)
    expect(document.body.textContent).toContain('Tab: box select')
    sp.hide()
    expect(tab(document.body)).toBe(false)
  } finally {
    sp.hide()
    canvas.remove()
    spy.mockRestore()
  }
})
