import { expect, it } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'

it('keeps simulated beads and slabs registered when visibility is refreshed, hidden, and restored', () => {
  const target = { helix_id: 'h', bp_index: 0, direction: 'FORWARD', copy: 0 }
  const nucleotide = {
    ...target, strand_id: 's', strand_type: 'staple', domain_index: 0,
    backbone_position: [1, 0, 0], base_position: [0.5, 0, 0],
    base_normal: [-1, 0, 0], axis_tangent: [0, 0, 1],
  }
  const design = { helices: [], strands: [{ id: 's', strand_type: 'staple', domains: [] }] }
  const ctrl = buildHelixObjects([nucleotide], design, new THREE.Scene())
  ctrl.applyFemPositions([{ ...target, backbone_position: [11, 5, -3], nx: -1, ny: 0, nz: 0, tx: 0, ty: 0, tz: 1 }])
  const before = ctrl.residueTransformInfo(target)
  expect(new THREE.Vector3().setFromMatrixPosition(before.beadMatrix).toArray()).toEqual([11, 5, -3])
  expect(new THREE.Vector3().setFromMatrixPosition(before.slabMatrix).x).toBeGreaterThan(10)
  ctrl.setHiddenNucs(new Set())
  expect(ctrl.residueTransformInfo(target).slabMatrix.elements).toEqual(before.slabMatrix.elements)
  ctrl.setHiddenNucs(new Set(['h:h']))
  ctrl.setHiddenNucs(new Set(['h:h']))
  ctrl.setHiddenNucs(new Set())
  const after = ctrl.residueTransformInfo(target)
  expect(after.slabMatrix.elements).toEqual(before.slabMatrix.elements)
  expect(after.beadMatrix.elements).toEqual(before.beadMatrix.elements)
})

it('renders measured trajectory slab centers instead of rotating the native offset', async () => {
  const { framesToUpdates } = await import('../ui/oxdna_display.js')
  const key = ['h', 0, 'FORWARD']
  const nuc = {
    helix_id:'h', bp_index:0, direction:'FORWARD', strand_id:'s',
    strand_type:'staple', domain_index:0, backbone_position:[1,0,0],
    base_position:[.5,0,0], base_normal:[-1,0,0], axis_tangent:[0,0,1],
  }
  const design = {helices:[], strands:[{id:'s',strand_type:'staple',domains:[]}]}
  const ctrl = buildHelixObjects([nuc], design, new THREE.Scene())
  const target = {helix_id:'h', bp_index:0, direction:'FORWARD', copy:0}
  const initial = ctrl.residueTransformInfo(target).slabMatrix.clone()
  const frame = [11,5,-3, -1,0,0, 0,1,0, 10.2,5.3,-2.8]
  ctrl.applyFemPositions(framesToUpdates([key], frame))
  const matrix = ctrl.residueTransformInfo(target).slabMatrix
  const position = new THREE.Vector3().setFromMatrixPosition(matrix)
  expect(position.distanceTo(new THREE.Vector3(...frame.slice(9)))).toBeLessThan(1e-6)
  const rotation = new THREE.Quaternion(), scale = new THREE.Vector3()
  matrix.decompose(new THREE.Vector3(), rotation, scale)
  expect(Math.abs(new THREE.Vector3(0,1,0).applyQuaternion(rotation).y)).toBeCloseTo(1)
  ctrl.setHiddenNucs(new Set(['h:h']))
  ctrl.setHiddenNucs(new Set())
  expect(ctrl.residueTransformInfo(target).slabMatrix.elements).toEqual(matrix.elements)
  ctrl.applyFemPositions(null)
  expect(ctrl.residueTransformInfo(target).slabMatrix.elements).toEqual(initial.elements)
  expect(nuc.base_position).toEqual([.5,0,0])
})
