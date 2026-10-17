import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initViewVolumes } from './view_volumes.js'

let ui
beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('requestAnimationFrame', callback => setTimeout(() => callback(performance.now()), 0))
  vi.stubGlobal('cancelAnimationFrame', id => clearTimeout(id))
  document.body.innerHTML = '<div id="right-tab-content-visualization"></div><canvas></canvas>'
})
afterEach(() => { ui?.dispose(); vi.unstubAllGlobals(); vi.useRealTimers(); document.body.replaceChildren() })
const volume = enabled => ({ id: 'v', name: 'Volume', enabled, representation: 'beads', opacity: 1,
  min_corner: [.5, -.5, -.5], max_corner: [1.5, .5, .5] })
function setup(volumes = []) {
  const data = { design: { helices: [{ id: 'h', loop_skips: [{ bp_index: 1, delta: -1 }] }] },
    nucleotides: [0, 2].map(bp => ({ helix_id: 'h', bp_index: bp, backbone_position: [bp, 0, 0] })) }
  const store = createMockStore({ assemblyActive: true, currentAssembly: { id: 'a', view_volumes: volumes,
    instances: [{ id: 'copy', representation: 'cylinders' }] } })
  let rebuilt
  const assemblyRenderer = { getInstanceRenderData: vi.fn(() => data), getLiveTransform: vi.fn(() => new THREE.Matrix4()),
    onRebuildComplete: callback => { rebuilt = callback } }
  const applyAssemblyLayers = vi.fn(), scene = new THREE.Scene()
  ui = initViewVolumes({ document, scene, camera: new THREE.PerspectiveCamera(), canvas: document.querySelector('canvas'),
    controls: {}, store, api: {}, designRenderer: { getBackboneEntries: vi.fn(() => []) }, assemblyRenderer, applyAssemblyLayers })
  return { store, data, assemblyRenderer, applyAssemblyLayers, scene, rebuilt: () => rebuilt() }
}

it('does no point or geometry work for absent/disabled volumes on store changes and renderer completion', async () => {
  const f = setup()
  await vi.advanceTimersByTimeAsync(125)
  f.store.setState({ currentAssembly: { ...f.store.getState().currentAssembly, view_volumes: [volume(false)],
    instances: [{ id: 'copy', representation: 'full' }] } })
  f.rebuilt()
  await vi.advanceTimersByTimeAsync(125)
  expect(f.assemblyRenderer.getInstanceRenderData).not.toHaveBeenCalled()
  expect(f.assemblyRenderer.getLiveTransform).not.toHaveBeenCalled()
  expect(f.applyAssemblyLayers).toHaveBeenLastCalledWith([])
  expect(ui.debug.layers()).toEqual([])
  expect(ui.debug.selectedMembership().count).toBe(0)
  expect(f.scene.getObjectByName('view-volumes').children).toHaveLength(1)
  expect(ui.debug.timing().last.pointCount).toBe(0)
})

it('applies active membership, observes in-place source changes on rebuild, then clears disabled layers', async () => {
  const f = setup([volume(true)])
  await vi.advanceTimersByTimeAsync(125)
  expect(f.applyAssemblyLayers.mock.lastCall[0][0].keys).toEqual(['copy|h:1'])
  f.data.nucleotides[0].backbone_position[0] = 10
  f.data.nucleotides[1].backbone_position[0] = 12
  f.rebuilt()
  await vi.advanceTimersByTimeAsync(125)
  expect(f.applyAssemblyLayers.mock.lastCall[0][0].keys).toEqual([])
  f.store.setState({ currentAssembly: { ...f.store.getState().currentAssembly, view_volumes: [volume(false)] } })
  await vi.advanceTimersByTimeAsync(125)
  const reads = f.assemblyRenderer.getInstanceRenderData.mock.calls.length
  f.rebuilt()
  await vi.advanceTimersByTimeAsync(125)
  expect(f.assemblyRenderer.getInstanceRenderData).toHaveBeenCalledTimes(reads)
  expect(f.applyAssemblyLayers).toHaveBeenLastCalledWith([])
})
