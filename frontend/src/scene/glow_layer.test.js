import { beforeAll, afterAll, describe, it, expect, vi } from 'vitest'
import { Scene, Vector3 } from 'three'
import * as THREE from 'three'

let createMultiColorGlowLayer, createGlowLayer, canvasMock
beforeAll(async () => {
  canvasMock = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    createRadialGradient: () => ({ addColorStop() {} }), fillRect() {},
  })
  ;({ createMultiColorGlowLayer, createGlowLayer } = await import('./glow_layer.js'))
})
afterAll(() => canvasMock.mockRestore())

describe('fluorescence intensity', () => {
  it('attenuates same-color donors independently and reuses materials across frames', () => {
    const scene = new Scene(), layer = createMultiColorGlowLayer(scene)
    const entry = brightness => ({ pos: new Vector3(), emissionColor: 0xff0000, brightness })
    layer.setEntries([entry(0.5), entry(1)])
    const [first, second] = scene.children.map(sprite => sprite.material)
    expect(first).not.toBe(second)
    expect(first.opacity).toBe(0.5)
    expect(second.opacity).toBe(1)
    layer.setEntries([entry(0), entry(0.25)])
    expect(scene.children[0].material).toBe(first)
    expect(first.opacity).toBe(0)
    expect(second.opacity).toBe(0.25)
    layer.setEntries([entry(undefined), entry(undefined)])
    expect(first.opacity).toBe(1)
    const disposed = vi.fn(); first.addEventListener('dispose', disposed)
    layer.clear()
    expect(disposed).toHaveBeenCalledOnce()
    expect(scene.children).toHaveLength(0)
  })
})

it('keeps idle glow buffers untouched and uploads only changed instance spans', () => {
  const scene = new THREE.Scene(), layer = createGlowLayer(scene)
  const entries = Array.from({ length: 1000 }, (_, i) => ({ pos: new THREE.Vector3(i, 0, 0) }))
  layer.setEntries(entries)
  const mesh = scene.children[0], attr = mesh.instanceMatrix, version = attr.version
  attr.clearUpdateRanges()
  for (let i = 0; i < 100; i++) layer.refresh()
  expect(attr.version).toBe(version)
  expect(attr.updateRanges).toEqual([])
  entries[500].pos.x = 750; layer.refresh()
  expect(attr.updateRanges).toEqual([{ start: 500 * 16, count: 16 }])
  entries[501].scale = .3; layer.refresh()
  expect(attr.updateRanges).toEqual([{ start: 500 * 16, count: 32 }])
  const matrix = new THREE.Matrix4(); mesh.getMatrixAt(500, matrix)
  expect(matrix.elements[12]).toBe(750)
  const lastVersion = attr.version; layer.clear()
  expect(mesh.count).toBe(0); expect(attr.version).toBe(lastVersion)
  layer.dispose(); expect(scene.children).toHaveLength(0)
})
it('disposes replaced instance buffers and reuses capacity for smaller selections', () => {
  const scene = new THREE.Scene(), layer = createGlowLayer(scene)
  const first = scene.children[0], disposed = vi.fn(); first.addEventListener('dispose', disposed)
  layer.setEntries([{ pos: new THREE.Vector3() }, { pos: new THREE.Vector3(1, 0, 0) }])
  expect(disposed).toHaveBeenCalledOnce()
  const mesh = scene.children[0]; layer.setEntries([{ pos: new THREE.Vector3(3, 0, 0) }])
  expect(scene.children[0]).toBe(mesh); expect(mesh.count).toBe(1)
  layer.dispose()
})
