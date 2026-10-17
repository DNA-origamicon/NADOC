import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { buildPartComparisonScene, initPartComparisonViewer } from './part_comparison_viewer.js'
import { comparisonBinding, comparisonEnvelope } from '../test-helpers/part_comparison.js'
import { dnaEnvelope } from '../test-helpers/part_dna_comparison.js'

const owned = vi.hoisted(() => ({ renderers: [], controls: [], observers: [] }))
vi.mock('three', async importOriginal => {
  const real = await importOriginal()
  return { ...real, WebGLRenderer: class {
    constructor() {
      this.domElement = document.createElement('canvas')
      for (const name of ['setSize', 'setPixelRatio', 'setScissorTest', 'setScissor', 'setViewport',
        'setClearColor', 'clear', 'render', 'dispose', 'forceContextLoss']) this[name] = vi.fn()
      owned.renderers.push(this)
    }
  } }
})
vi.mock('three/addons/controls/OrbitControls.js', async () => {
  const { EventDispatcher, Vector3 } = await import('three')
  return { OrbitControls: class extends EventDispatcher {
    constructor(camera, canvas) {
      super(); this.camera = camera; this.domElement = canvas; this.target = new Vector3()
      this.update = vi.fn(); this.dispose = vi.fn(); owned.controls.push(this)
    }
  } }
})

const scenes = [], viewers = []
const geometries = scene => { const values = []; scene.traverse(node => { if (node.geometry) values.push(node) }); return values }
function host() {
  const element = document.createElement('div')
  Object.defineProperties(element, { clientWidth: { value: 800 }, clientHeight: { value: 400 } })
  document.body.append(element)
  return element
}
function build(pane) { const result = buildPartComparisonScene(pane); scenes.push(result); return result }
function open(element = host(), packet = comparisonEnvelope(), binding = comparisonBinding()) {
  const result = initPartComparisonViewer(element, packet, binding); viewers.push(result); return result
}

beforeEach(() => {
  owned.renderers.length = owned.controls.length = owned.observers.length = 0
  vi.stubGlobal('requestAnimationFrame', vi.fn())
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback) { this.callback = callback; this.observe = vi.fn(); this.disconnect = vi.fn(); owned.observers.push(this) }
  })
})
afterEach(() => {
  for (const viewer of viewers.splice(0)) viewer.dispose()
  for (const scene of scenes.splice(0)) scene.dispose()
  document.body.replaceChildren(); vi.unstubAllGlobals(); vi.restoreAllMocks()
})

describe('owned coarse authored geometry', () => {
  it('uses native particle diameter and row-major pose in the same nm frame as protein atoms', () => {
    const pane = comparisonEnvelope().published, original = JSON.stringify(pane), { scene } = build(pane)
    const meshes = geometries(scene), gold = meshes.find(mesh => mesh.userData.nanoparticleId === 'gold')
    expect(gold.geometry.parameters.radius).toBe(5)
    expect(gold.position.toArray()).toEqual([4, -2, 3])
    gold.updateMatrixWorld(true)
    const placedAxis = new THREE.Vector3(1, 0, 0).applyMatrix4(gold.matrixWorld)
    expect(placedAxis.x).toBeCloseTo(4); expect(placedAxis.y).toBeCloseTo(-1); expect(placedAxis.z).toBeCloseTo(3)
    expect(gold.visible).toBe(true) // scope deliberately shows all authored placements
    expect(gold.userData.authoredVisible).toBe(false)
    const protein = meshes.find(mesh => mesh.name === 'proteinTrace')
    protein.geometry.computeBoundingBox()
    const center = protein.geometry.boundingBox.getCenter(new THREE.Vector3())
    expect(center.x).toBeCloseTo(2); expect(center.y).toBeCloseTo(-1); expect(center.z).toBeCloseTo(6)
    expect(JSON.stringify(pane)).toBe(original)
  })

  it('shows QD color and existing no-CA ovoid fallback without dropping either family', () => {
    const pane = comparisonEnvelope().published
    pane.particles[0] = { ...pane.particles[0], kind: 'quantum_dot', display_color: '#32a862' }
    pane.proteins[0].representation = 'ovoid'; pane.proteins[0].atoms[0].name = 'N'
    const { scene } = build(pane), meshes = geometries(scene)
    expect(meshes.find(mesh => mesh.userData.nanoparticleId === 'gold').material.color.getHexString()).toBe('32a862')
    expect(meshes.some(mesh => mesh.name === 'proteinOvoid')).toBe(true)
  })

  it('disposes every exclusively owned geometry/material exactly once and leaves unrelated scenes alone', () => {
    const result = build(comparisonEnvelope().published), meshes = geometries(result.scene)
    const geometrySpies = [...new Set(meshes.map(mesh => mesh.geometry))].map(value => vi.spyOn(value, 'dispose'))
    const materialSpies = [...new Set(meshes.flatMap(mesh => Array.isArray(mesh.material) ? mesh.material : [mesh.material]))]
      .map(value => vi.spyOn(value, 'dispose'))
    const live = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial())
    const liveGeometry = vi.spyOn(live.geometry, 'dispose'), liveMaterial = vi.spyOn(live.material, 'dispose')
    result.dispose(); result.dispose()
    for (const dispose of [...geometrySpies, ...materialSpies]) expect(dispose).toHaveBeenCalledOnce()
    expect(geometries(result.scene)).toHaveLength(0)
    expect(liveGeometry).not.toHaveBeenCalled(); expect(liveMaterial).not.toHaveBeenCalled()
    live.geometry.dispose(); live.material.dispose()
  })
})

describe('static comparison viewport ownership', () => {
  it('composes native DNA and existing asset layers in both private panes without a second context', () => {
    const packet = dnaEnvelope(), original = JSON.stringify(packet)
    const viewer = open(host(), packet, { ...comparisonBinding(), projectionVersion: 2 })
    const rendered = owned.renderers[0].render.mock.calls
    expect(rendered).toHaveLength(2)
    for (const [scene] of rendered) {
      expect(scene.getObjectByName('privateDnaComparison')).toBeTruthy()
      expect(geometries(scene).some(mesh => mesh.userData.nanoparticleId === 'gold')).toBe(true)
    }
    expect(owned.renderers).toHaveLength(1)
    expect(JSON.stringify(packet)).toBe(original)
    viewer.dispose()
    for (const [scene] of rendered) expect(scene.children).toHaveLength(0)
  })

  it('cleans the first DNA pane if the second has an unrepresented native connection', () => {
    const packet = dnaEnvelope()
    packet.proposed.dna.display_topology.forced_ligations = [{ id: 'f', three_prime_helix_id: 'h', three_prime_bp: 0,
      three_prime_direction: 'FORWARD', five_prime_helix_id: 'h', five_prime_bp: 0,
      five_prime_direction: 'FORWARD', extra_bases: null, is_periodic_seam: false }]
    const disposed = vi.spyOn(THREE.Material.prototype, 'dispose')
    expect(() => open(host(), packet, { ...comparisonBinding(), projectionVersion: 2 })).toThrow(/authored ligation/)
    expect(owned.renderers).toHaveLength(0)
    expect(disposed).toHaveBeenCalled()
    expect(document.querySelectorAll('canvas')).toHaveLength(0)
  })

  it('uses one GPU context and two scenes with a shared camera and frame, rendering only on demand', () => {
    open()
    expect(owned.renderers).toHaveLength(1); expect(owned.controls).toHaveLength(1)
    const renderer = owned.renderers[0], calls = renderer.render.mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[0][0]).not.toBe(calls[1][0])
    expect(calls[0][1]).toBe(calls[1][1])
    expect(calls[0][1].aspect).toBe(1)
    expect(renderer.setScissor).toHaveBeenCalledWith(0, 0, 400, 400)
    expect(renderer.setScissor).toHaveBeenCalledWith(400, 0, 400, 400)
    expect(globalThis.requestAnimationFrame).not.toHaveBeenCalled()
    renderer.render.mockClear()
    owned.controls[0].dispatchEvent({ type: 'change' })
    expect(renderer.render).toHaveBeenCalledTimes(2)
  })

  it('refuses an incomplete or malformed second pane before allocating any GPU context', () => {
    const packet = comparisonEnvelope(); packet.proposed.proteins[0].atoms[0].x = NaN
    expect(() => open(host(), packet)).toThrow()
    expect(owned.renderers).toHaveLength(0)
    expect(document.querySelectorAll('canvas')).toHaveLength(0)
  })

  it('disposes GPU resources, observer, controls, canvas and listeners on close', () => {
    const element = host(), viewer = open(element), renderer = owned.renderers[0], controls = owned.controls[0]
    const meshes = renderer.render.mock.calls.flatMap(([scene]) => geometries(scene))
    const resources = [...new Set(meshes.flatMap(mesh => [mesh.geometry, mesh.material]))]
    const spies = resources.map(resource => vi.spyOn(resource, 'dispose'))
    viewer.dispose(); viewer.dispose()
    for (const dispose of spies) expect(dispose).toHaveBeenCalledOnce()
    expect(owned.observers[0].disconnect).toHaveBeenCalledOnce()
    expect(controls.dispose).toHaveBeenCalledOnce()
    expect(renderer.dispose).toHaveBeenCalledOnce(); expect(renderer.forceContextLoss).toHaveBeenCalledOnce()
    expect(element.querySelector('canvas')).toBeNull()
    renderer.render.mockClear()
    controls.dispatchEvent({ type: 'change' }); owned.observers[0].callback()
    renderer.domElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'f' }))
    expect(renderer.render).not.toHaveBeenCalled()
  })

  it('releases the window resize fallback after unmount', () => {
    vi.stubGlobal('ResizeObserver', undefined)
    const viewer = open(), renderer = owned.renderers[0]
    renderer.render.mockClear(); window.dispatchEvent(new Event('resize'))
    expect(renderer.render).toHaveBeenCalledTimes(2)
    viewer.dispose(); renderer.render.mockClear(); window.dispatchEvent(new Event('resize'))
    expect(renderer.render).not.toHaveBeenCalled()
  })

  it('cleans up resources when initial drawing fails instead of leaking a half-open viewer', () => {
    const sceneDisposed = vi.spyOn(THREE.BufferGeometry.prototype, 'dispose')
    // Failure after renderer/control/scene construction exercises their rollback.
    const originalPush = owned.renderers.push
    const push = vi.spyOn(owned.renderers, 'push').mockImplementation(function (renderer) {
      renderer.render.mockImplementation(() => { throw new Error('GPU draw failed') })
      return originalPush.call(this, renderer)
    })
    const element = host()
    expect(() => open(element)).toThrow('GPU draw failed')
    push.mockRestore()
    expect(owned.renderers[0].dispose).toHaveBeenCalledOnce()
    expect(owned.renderers[0].forceContextLoss).toHaveBeenCalledOnce()
    expect(owned.controls[0].dispose).toHaveBeenCalledOnce()
    expect(sceneDisposed).toHaveBeenCalled()
    expect(element.querySelector('canvas')).toBeNull()
  })
})
