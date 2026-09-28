// @vitest-environment jsdom
import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { initAssemblyViewVolumes } from './assembly_view_volumes.js'
import { buildAssemblyVisualization } from './assembly_visualization.js'
vi.mock('./assembly_visualization.js', () => ({ buildAssemblyVisualization: vi.fn() }))

it('rejects stale async volumes and restores native assembly when disabled', async () => {
  const scene = new THREE.Scene(), state = { assemblyActive: true, currentAssembly: { id: 'a' } }
  const native = { setVisible: vi.fn() }, make = () => { const s = new THREE.Scene(); s.disposeVisualization = vi.fn(); return s }
  let release
  buildAssemblyVisualization.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
  const manager = initAssemblyViewVolumes({ scene, store: { getState: () => state }, api: {}, assemblyRenderer: native })
  const pending = manager.update([{ id: 'old' }])
  await new Promise(resolve => setTimeout(resolve, 0))
  const latest = make()
  latest.visualizationBounds = new THREE.Box3(new THREE.Vector3(-10,-2,-3), new THREE.Vector3(30,4,5))
  buildAssemblyVisualization.mockResolvedValueOnce(latest)
  const next = manager.update([{ id: 'latest' }])
  const stale = make(); release(stale); await pending; await next
  expect(stale.disposeVisualization).toHaveBeenCalledOnce()
  expect(scene.children).toEqual([latest])
  expect(native.setVisible).toHaveBeenLastCalledWith(false)
  expect(manager.getBoundingBox().equals(latest.visualizationBounds)).toBe(true)
  await manager.update([])
  expect(latest.disposeVisualization).toHaveBeenCalledOnce()
  expect(scene.children).toEqual([])
  expect(native.setVisible).toHaveBeenLastCalledWith(true)
  manager.dispose()
})
