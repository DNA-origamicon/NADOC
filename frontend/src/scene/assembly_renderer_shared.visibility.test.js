import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { _createSharedInstancingRenderer } from './assembly_renderer_shared.js'

it('removes source trees from render traversal while an external result owns the view', async () => {
  const assembly = { instances: [{ id: 'part', source: { type: 'file', path: 'part.nadoc' },
    representation: 'beads', transform: { values: new THREE.Matrix4().elements }, visible: true }] }
  const scene = new THREE.Scene()
  const design = { helices: [], strands: [{ id: 's', strand_type: 'staple', domains: [] }], crossovers: [] }
  const nucleotides = [0,1].map(i => ({ helix_id: 'h', bp_index: i, direction: 'FORWARD', copy: 0,
    strand_id: 's', strand_type: 'staple', domain_index: 0, backbone_position: [1,0,i],
    placement_source: 'native-full-o5-v1', slab_position: [.67,0,i], slab_quaternion: [-.5,.5,.5,.5], base_position: [0.5,0,i], base_normal: [-1,0,0], axis_tangent: [0,0,1] }))
  const store = { getState: () => ({ currentAssembly: assembly }), subscribe: vi.fn() }
  const api = { getAssemblyGeometry: async () => ({ instances: { part: { design, nucleotides, helix_axes: {} } } }) }
  const renderer = _createSharedInstancingRenderer({ scene, store, api })
  await renderer.rebuild(assembly)
  const source = () => scene.children.find(o => o.userData.sharedSource)
  expect(source()?.visible).toBe(true)
  renderer.setVisible(false)
  expect(source().visible).toBe(false)
  await renderer.rebuild(assembly)
  expect(source().visible).toBe(false)
  renderer.setVisible(true)
  expect(source().visible).toBe(true)
  expect(assembly.instances[0].visible).toBe(true)
  renderer.dispose()
})
