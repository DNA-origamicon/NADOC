import { beforeEach, describe, expect, it, vi } from 'vitest'
import { JSDOM } from 'jsdom'
import * as THREE from 'three'
import { designGeometryBounds, designLongestDimension, initMultiOverlay, overlayOffsets, overlayRenderOrder } from './multi_overlay.js'

describe('multi-overlay', () => {
  beforeEach(() => {
    const dom = new JSDOM('<div id="right-multi-overlay-body"></div><div><canvas id="canvas"></canvas></div>')
    globalThis.document = dom.window.document
  })

  it('spaces layers evenly across one longest-dimension interval per step', () => {
    expect(overlayOffsets(1, 1, 20)).toEqual([0])
    expect(overlayOffsets(2, 1, 20)).toEqual([-10, 10])
    expect(overlayOffsets(3, .5, 20)).toEqual([-10, 0, 10])
    expect(overlayOffsets(4, 0, 20)).toEqual([-0, -0, 0, 0])
  })

  it('measures separation from the design geometry rather than representation thickness', () => {
    expect(designLongestDimension({ currentGeometry: [
      { backbone_position: [-5, 2, 1] }, { axis_position: [15, 4, 8] },
    ] })).toBe(20)
  })

  it('uses stable current-design bounds independently of representation thickness', () => {
    const box = designGeometryBounds({ currentGeometry: [
      { axis_position: [-5, 1, 2] }, { backbone_position: [15, 4, 8] },
    ] })
    expect(box.getSize(new THREE.Vector3()).toArray()).toEqual([20, 3, 6])
    expect(designGeometryBounds({ assemblyActive: true, currentGeometry: [{ axis_position: [1, 2, 3] }] }).isEmpty()).toBe(true)
  })

  it('reverses transparent scene order when viewing separated layers from opposite sides', () => {
    const layers = [-2, 0, 2].map(x => {
      const renderScene = new THREE.Scene(); renderScene.position.x = x
      return { renderScene }
    })
    const camera = new THREE.PerspectiveCamera()
    camera.position.set(10, 0, 0); camera.lookAt(0, 0, 0)
    expect(overlayRenderOrder(layers, 3, camera)).toEqual([0, 1, 2])
    camera.position.set(-10, 0, 0); camera.lookAt(0, 0, 0)
    expect(overlayRenderOrder(layers, 3, camera)).toEqual([2, 1, 0])
  })

  it('creates 1-4 controls and numbered in-viewport layer rows', async () => {
    const canvas = document.getElementById('canvas')
    Object.defineProperties(canvas, { clientWidth: { value: 800 }, clientHeight: { value: 600 } })
    const scene = new THREE.Scene()
    scene.add(new THREE.Mesh(new THREE.BoxGeometry(2, 3, 4), new THREE.MeshBasicMaterial()))
    const camera = new THREE.PerspectiveCamera(55, 1, .1, 100)
    const renderer = { autoClear: true, setViewport: vi.fn(), setScissorTest: vi.fn(), render: vi.fn(), getPixelRatio: () => 1 }
    let renderFn
    const api = initMultiOverlay({
      document, scene, camera, renderer, canvas,
      controls: { target: new THREE.Vector3(), update: vi.fn() },
      store: { getState: () => ({ currentGeometry: [] }) },
      setRenderFn: fn => { renderFn = fn }, resetRenderFn: vi.fn(),
      setRepresentation: vi.fn(), setColoringMode: vi.fn(),
    })
    expect(document.querySelectorAll('.mo-count-btn')).toHaveLength(4)
    await api.activate(4)
    expect(api.layers.map(layer => layer.representation)).toEqual([
      'hull-prism', 'cylinders', 'mrdna-fine', 'full',
    ])
    await vi.waitFor(() => expect(document.querySelectorAll('.mo-layer-row[data-ready="true"]')).toHaveLength(4))
    expect(document.querySelectorAll('.mo-representation')).toHaveLength(4)
    expect([...document.querySelector('.mo-representation').options].map(option => option.value))
      .toEqual(expect.arrayContaining(['mrdna-coarse', 'mrdna-fine', 'oxdna']))
    expect(document.querySelectorAll('.mo-coloring')).toHaveLength(4)
    expect(document.querySelectorAll('.mo-opacity')).toHaveLength(4)
    const opacity = document.querySelectorAll('.mo-opacity')[1]
    opacity.value = '0.35'; opacity.dispatchEvent(new Event('input', { bubbles: true }))
    let layerMaterial
    api.layers[1].renderScene.traverse(obj => { if (obj.material) layerMaterial = obj.material })
    expect(layerMaterial.opacity).toBeCloseTo(0.35)
    const separation = document.querySelector('.mo-separation-row input')
    separation.value = '1'; separation.dispatchEvent(new Event('input', { bubbles: true }))
    expect(api.layers.map(layer => layer.renderScene.position.x)).toEqual([-6, -2, 2, 6])
    renderFn()
    expect(renderer.render).toHaveBeenCalledTimes(4)
  })
})
