import { beforeAll, afterAll, describe, it, expect, vi } from 'vitest'
import { Scene, Vector3 } from 'three'

let createMultiColorGlowLayer, canvasMock
beforeAll(async () => {
  canvasMock = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    createRadialGradient: () => ({ addColorStop() {} }), fillRect() {},
  })
  ;({ createMultiColorGlowLayer } = await import('./glow_layer.js'))
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
