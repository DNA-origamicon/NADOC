// @vitest-environment node
import { expect, it } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'

it('keeps separately moved axis sections in place through display refresh and deformation toggles', () => {
  const scene = new THREE.Scene()
  const segments = [
    { bp_lo: 0, bp_hi: 5, start: [0, 10, 0], end: [0, 10, 2] },
    { bp_lo: 6, bp_hi: 11, start: [0, -5, 2], end: [0, -5, 4] },
  ]
  const axes = { h: { start: [0, 0, 0], end: [0, 0, 4], samples: [[0, 0, 0], [0, 0, 4]], segments, residue_transformed: true } }
  const design = { helices: [{ id: 'h', bp_start: 0, length_bp: 12, axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 4 } }], strands: [] }
  const ctrl = buildHelixObjects([], design, scene, {}, [], axes)
  const positions = () => { const p = []; scene.traverse(o => { if (o.name === 'axisLine') p.push(o.position.toArray()) }); return p }
  expect(positions()).toEqual([[0, 10, 1], [0, -5, 3]])
  const straight = new Map([['h', { start: new THREE.Vector3(), end: new THREE.Vector3(0, 0, 4), segments }]])
  for (const t of [0, .5, 1]) {
    ctrl.applyDeformLerp(new Map(), straight, new Map(), null, t)
    expect(positions()).toEqual([[0, 10, 1], [0, -5, 3]])
  }
})
