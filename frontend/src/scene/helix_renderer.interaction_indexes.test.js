import { expect, it } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'

it('preserves repeated-site copy selection and colors when interaction indexes initialize lazily', () => {
  const geometry = [0, 1].map(copy_k => ({
    helix_id: 'h', bp_index: 0, direction: 'FORWARD', copy_k,
    strand_id: 's', strand_type: 'staple', domain_index: 0,
    backbone_position: [copy_k + 1, 0, 0], base_position: [copy_k + .5, 0, 0],
    placement_source: 'native-full-o5-v1', slab_position: [copy_k + .67, 0, 0],
    slab_quaternion: [0, Math.SQRT1_2, Math.SQRT1_2, 0], base_normal: [-1, 0, 0], axis_tangent: [0, 0, 1],
  }))
  const scene = new THREE.Scene()
  const design = { helices: [], strands: [{ id: 's', strand_type: 'staple', domains: [] }] }
  const ctrl = buildHelixObjects(geometry, design, scene)
  const matrices = ctrl.backboneEntries[0].instMesh.instanceMatrix.array.slice()
  expect(ctrl.backboneEntries.map(entry => entry._copy)).toEqual([0, 1])
  expect(ctrl.lookupEntry('h:0:FORWARD')).toBe(ctrl.backboneEntries[1])
  for (const copy of [0, 1]) {
    const info = ctrl.residueTransformInfo({ helix_id: 'h', bp_index: 0, direction: 'FORWARD', copy })
    expect(info.bead).toBe(ctrl.backboneEntries[copy])
    expect(info.slab).toBe(ctrl.slabEntries[copy])
  }
  ctrl.applyScalarColors({ 'h:0:FORWARD:0': 0xff0000, 'h:0:FORWARD:1': 0x00ff00 })
  const color = new THREE.Color()
  ctrl.backboneEntries.forEach((entry, index) => {
    entry.instMesh.getColorAt(entry.id, color)
    expect(color.getHex()).toBe(index ? 0x00ff00 : 0xff0000)
  })
  expect(ctrl.backboneEntries[0].instMesh.instanceMatrix.array).toEqual(matrices)
  scene.traverse(object => {
    if (object.geometry && !object.geometry.userData?.shared) object.geometry.dispose()
    for (const material of Array.isArray(object.material) ? object.material : object.material ? [object.material] : []) material.dispose()
  })
})
