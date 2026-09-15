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
