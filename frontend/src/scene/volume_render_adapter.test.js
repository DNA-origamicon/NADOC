import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { combineAtomRenderers, combineSurfaceRenderers, coarseVolumePicker } from './volume_render_adapter.js'

it('picks the nearest atom across independently rendered volumes', () => {
  const renderer = distance => ({ getMode: () => 'vdw', raycastPick: () => ({ distance }), highlight: vi.fn() })
  const base = renderer(5), local = renderer(2), layers = [local]
  const combined = combineAtomRenderers(base, () => layers)
  expect(combined.raycastPick({}).distance).toBe(2)
  combined.highlight('selection')
  expect(local.highlight).toHaveBeenCalledWith('selection')
  layers.length = 0
  expect(combined.raycastPick({}).distance).toBe(5)
})

it('routes surface face metadata to the surface that was hit', () => {
  const make = (z, id) => {
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.MeshBasicMaterial())
    mesh.position.z = z; mesh.updateMatrixWorld()
    return { getMesh: () => mesh, getMode: () => 'on', strandIdAt: () => id }
  }
  const base = make(0, 'base'), local = make(2, 'local')
  const combined = combineSurfaceRenderers(base, () => [local])
  const ray = new THREE.Raycaster(new THREE.Vector3(0, 0, 5), new THREE.Vector3(0, 0, -1))
  const hits = ray.intersectObject(combined.getMesh(), false)
  expect(hits.length).toBeGreaterThan(1)
  expect(combined.strandIdAt(hits[0].face)).toBe('local')
  expect(combined.strandIdAt(hits.at(-1).face)).toBe('base')
})

it('ignores hidden CG instances and returns the visible nucleotide', () => {
  const root = new THREE.Group(), mesh = new THREE.Mesh()
  root.add(mesh)
  mesh.geometry.setAttribute('instanceAlpha', new THREE.InstancedBufferAttribute(new Float32Array([0, 1]), 1))
  const nuc = { helix_id: 1, bp_index: 2, backbone_position: [0, 0, 0] }
  const picker = coarseVolumePicker({ root }, new Set(['1:2']), [nuc])
  const hits = [0, 1].map(instanceId => ({ object: mesh, instanceId, distance: instanceId + 1, point: new THREE.Vector3() }))
  expect(picker.raycastPick({ intersectObjects: () => hits })).toEqual({ atom: nuc, distance: 2 })
})
