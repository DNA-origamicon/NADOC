import { beforeEach, describe, expect, it, vi } from 'vitest'
import { JSDOM } from 'jsdom'
import * as THREE from 'three'
import { cloneMultiScene, initMultiView, MULTI_VIEW_REPRESENTATIONS, multiViewContentBounds, multiViewDesignCentroid, multiViewRects } from './multi_view.js'

describe('multi-view', () => {
  beforeEach(() => {
    const dom = new JSDOM('<div id="right-multi-view-body"></div><div id="area"><canvas id="canvas"></canvas></div>')
    globalThis.document = dom.window.document
  })

  it('computes gap-free responsive layouts', () => {
    expect(multiViewRects(2, 901, 601)).toEqual([
      { x: 0, y: 0, w: 450, h: 601 }, { x: 450, y: 0, w: 451, h: 601 },
    ])
    expect(multiViewRects(3, 900, 600)).toHaveLength(3)
    expect(multiViewRects(4, 900, 600)).toHaveLength(4)
  })

  it('fits molecular geometry while excluding Hull-Audit-style helpers', () => {
    const root = new THREE.Group()
    const molecular = new THREE.Mesh(new THREE.BoxGeometry(2, 4, 6))
    molecular.position.set(10, 20, 30); root.add(molecular)
    const axes = new THREE.AxesHelper(1000); axes.position.set(-500, -500, -500); root.add(axes)
    const box = multiViewContentBounds(root)
    expect(box.getCenter(new THREE.Vector3()).toArray()).toEqual([10, 20, 30])
    expect(box.getSize(new THREE.Vector3()).toArray()).toEqual([2, 4, 6])
  })

  it('uses the arithmetic nucleotide centroid as the shared orbit target', () => {
    const fallback = new THREE.Vector3(99, 99, 99)
    const centroid = multiViewDesignCentroid({ currentGeometry: [
      { backbone_position: [0, 0, 0] },
      { axis_position: [3, 6, 9] },
      { base_position: [6, 0, 3] },
    ] }, fallback)
    expect(centroid.toArray()).toEqual([3, 2, 4])
    expect(multiViewDesignCentroid({ assemblyActive: true }, fallback).toArray()).toEqual([99, 99, 99])
  })

  it('preserves instance-only colors when cloning comparison scenes', () => {
    const scene = new THREE.Scene()
    const source = new THREE.InstancedMesh(
      new THREE.SphereGeometry(1), new THREE.MeshBasicMaterial({ color: 0xffffff }), 1)
    source.setColorAt(0, new THREE.Color(0xff3333))
    scene.add(source)
    const clone = cloneMultiScene(scene).children[0]
    const color = new THREE.Color()
    clone.getColorAt(0, color)
    expect(color.getHex()).toBe(0xff3333)
    expect(clone.material.vertexColors).toBe(false)
    expect(clone.geometry.getAttribute('color')).toBeUndefined()
  })

  it('creates configuration icons and per-panel representation/color selectors', async () => {
    const canvas = document.getElementById('canvas')
    Object.defineProperties(canvas, { clientWidth: { value: 900 }, clientHeight: { value: 600 } })
    const scene = new THREE.Scene()
    const renderer = { setScissorTest: vi.fn(), setViewport: vi.fn(), setScissor: vi.fn(), render: vi.fn(), getPixelRatio: () => 1 }
    let renderFn
    const api = initMultiView({
      document, scene, camera: new THREE.PerspectiveCamera(55, 1, .1, 100), renderer, canvas,
      controls: { target: new THREE.Vector3(), update: vi.fn(), enabled: true },
      store: { getState: () => ({ assemblyActive: false }) },
      setRenderFn: fn => { renderFn = fn }, resetRenderFn: vi.fn(),
      setRepresentation: vi.fn(), setColoringMode: vi.fn(),
    })
    expect(document.querySelectorAll('.mv-layout-btn')).toHaveLength(3)
    await api.activate(3)
    expect(api.panels.map(panel => panel.representation)).toEqual([
      'hull-prism', 'cylinders', 'mrdna-fine', 'full',
    ])
    expect(api.panels.slice(0, 3).every(panel => panel.camera.fov === 38)).toBe(true)
    expect(document.querySelectorAll('.mv-viewport-panel')).toHaveLength(3)
    expect(document.querySelectorAll('.mv-viewport-grid .mv-representation')).toHaveLength(3)
    expect(document.querySelectorAll('.mv-viewport-grid .mv-coloring')).toHaveLength(3)
    expect(MULTI_VIEW_REPRESENTATIONS).toContainEqual(['mrdna-coarse', 'mrDNA Coarse'])
    expect(MULTI_VIEW_REPRESENTATIONS).toContainEqual(['mrdna-fine', 'mrDNA Fine'])
    expect(MULTI_VIEW_REPRESENTATIONS).toContainEqual(['oxdna', 'oxDNA'])
    renderFn()
    expect(renderer.render).toHaveBeenCalledTimes(3)
  })
})
