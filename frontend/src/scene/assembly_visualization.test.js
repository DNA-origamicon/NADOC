import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { assemblyVolumePoints, unhideAssemblyVisualization } from './assembly_visualization.js'
import { resolveViewVolumeLayers } from './view_volumes.js'

it('namespaces repeated columns and applies instance transforms before volume membership', () => {
  const instances = [{ id: 'a' }, { id: 'b' }, { id: 'hidden', visible: false }]
  const renderer = {
    getInstanceRenderData: () => ({ design: { helices: [] }, nucleotides: [{ helix_id: 'h', bp_index: 2, backbone_position: [1, 0, 0] }] }),
    getLiveTransform: id => new THREE.Matrix4().makeTranslation(id === 'b' ? 20 : 0, 0, 0),
  }
  const points = assemblyVolumePoints({ instances }, renderer)
  expect(points).toEqual([{ key: 'a|h:2', position: [1, 0, 0] }, { key: 'b|h:2', position: [21, 0, 0] }])
  const volume = { id: 'v', shape: 'box', min_corner: [20,-1,-1], max_corner: [22,1,1], rotation: [0,0,0,1] }
  expect([...resolveViewVolumeLayers([volume], points)[0].keys]).toEqual(['b|h:2'])
})

it('Unhide All restores instance/group visibility without part API writes', async () => {
  const api = { batchPatchInstances: vi.fn(), patchGroup: vi.fn() }
  await unhideAssemblyVisualization({ api, store: { getState: () => ({ currentAssembly: {
    instances: [{ id: 'a', visible: false }, { id: 'b', visible: true }],
    groups: [{ id: 'g', visible: false }, { id: 'shown', visible: true }],
  } }) } })
  expect(api.batchPatchInstances).toHaveBeenCalledExactlyOnceWith([{ id: 'a', visible: true }])
  expect(api.patchGroup).toHaveBeenCalledExactlyOnceWith('g', { visible: true })
})
