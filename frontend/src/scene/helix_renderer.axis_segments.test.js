// @vitest-environment node
import { expect, it } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'
import { setNativePoseMap } from '../viewer/native_placement.js'

it('keeps stationary and moved straight-axis segments separate through history redraw and interpolation', () => {
  const design = { helices: [{ id: 'h', bp_start: 0, length_bp: 8,
    axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 2.672 } }], strands: [] }
  const segments = [
    { strand_id: 'a', domain_index: 0, bp_lo: 0, bp_hi: 3, start: [5, 0, 0], end: [5, 0, 1.336] },
    { strand_id: 'b', domain_index: 0, bp_lo: 4, bp_hi: 7, start: [0, 0, 1.336], end: [0, 0, 2.672] },
  ]
  const axes = { h: { start: [5, 0, 0], end: [5, 0, 2.672], segments } }
  const scene = new THREE.Scene()
  const ctrl = buildHelixObjects([], design, scene, {}, [], axes)
  const lines = []
  scene.traverse(o => { if (o.name === 'axisLine') lines.push(o) })
  const straight = new Map([['h', { start: new THREE.Vector3(0, 0, 0), end: new THREE.Vector3(0, 0, 2.672),
    segments: segments.map(s => ({ ...s, start: [0, 0, s.start[2]], end: [0, 0, s.end[2]] })) }]])
  expect(lines).toHaveLength(2)
  for (const t of [1, 0, .5, 1]) {
    ctrl.applyDeformLerp(new Map(), straight, new Map(), new Map(), t)
    expect(lines.map(o => o.position.x)).toEqual([5 * t, 0])
    expect(lines.map(o => o.position.z)).toEqual([.668, 2.004])
  }
  const posMap = new Map()
  for (let bp = 0; bp < 8; bp++) {
    const point = [0, 0, bp * .334]
    setNativePoseMap(posMap, new THREE.Vector3(...point), { helix_id: 'h', bp_index: bp, direction: 'FORWARD',
      placement_source: 'native-full-o5-v1', backbone_position: point, base_position: point,
      slab_position: point, slab_quaternion: [0, 0, 0, 1], base_normal: [1, 0, 0], axis_tangent: [0, 0, 1] })
  }
  const from = { posMap, axesMap: straight, bnMap: new Map() }
  const to = { posMap, axesMap: new Map([['h', { ...axes.h, start: new THREE.Vector3(...axes.h.start), end: new THREE.Vector3(...axes.h.end) }]]), bnMap: new Map() }
  for (const t of [0, .5, 1]) {
    ctrl.applyPositionLerp(from, to, t)
    expect(lines.map(o => o.position.x)).toEqual([5 * t, 0])
  }
  ctrl.revertToGeometry()
  expect(lines.map(o => o.position.x)).toEqual([5, 0])
  scene.traverse(o => { o.geometry?.dispose(); o.material?.dispose() })
})
