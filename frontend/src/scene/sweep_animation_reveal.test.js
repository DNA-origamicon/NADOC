import { it, expect } from 'vitest'
import * as THREE from 'three'
import { sweepAnimationReveal, revealSweepTube } from './sweep_animation_reveal.js'
const empty = { displayDesign: { deformations: [] } }
const sweep = direction => ({ displayDesign: { deformations: [{ id: 'sweep', type: 'sweep', affected_helix_ids: ['h'], plane_a_bp: 10, plane_b_bp: 19, params: { direction } }] } })
const nuc = bp_index => ({ helix_id: 'h', bp_index })
it('reveals from path origin, leaves existing material alone, and reverses exactly', () => {
  const reveal = sweepAnimationReveal(empty, sweep(1), .25)
  expect([10, 12, 13, 19].map(bp => reveal.scale(nuc(bp)))).toEqual([1, .5, 0, 0])
  expect(reveal.scale({ helix_id: 'old', bp_index: 19 })).toBe(1)
  const reverse = sweepAnimationReveal(sweep(1), empty, .75)
  expect([10, 12, 19].map(bp => reverse.scale(nuc(bp)))).toEqual([1, .5, 0])
  expect(sweepAnimationReveal(sweep(1), sweep(1), .5)).toBeNull()
})
it('honors sweeps authored from a source start toward lower bp', () => {
  const reveal = sweepAnimationReveal(empty, sweep(-1), .25)
  expect([19, 17, 16, 10].map(bp => reveal.scale(nuc(bp)))).toEqual([1, .5, 0, 0])
})
it('clips curved tubes in path order and restores their complete draw range', () => {
  const geometry = new THREE.TubeGeometry(new THREE.LineCurve3(new THREE.Vector3(), new THREE.Vector3(0, 0, 10)), 10, .2, 6)
  const mesh = new THREE.Mesh(geometry)
  const range = { lo: 10, hi: 19, reverse: false, progress: .5 }
  revealSweepTube(mesh, range, 10, 19)
  expect(geometry.drawRange.start).toBe(0)
  expect(geometry.drawRange.count).toBe(geometry.index.count / 2)
  revealSweepTube(mesh, { ...range, reverse: true }, 10, 19)
  expect(geometry.drawRange.start).toBe(geometry.index.count / 2)
  revealSweepTube(mesh, null, 10, 19)
  expect(geometry.drawRange.count).toBe(Infinity)
})
it('reveals surface triangles using nucleotide identity, including existing material', async () => {
  const { revealSweepSurface } = await import('./sweep_animation_reveal.js')
  const frame = { faces: [0, 1, 2, 3, 4, 5, 6, 7, 8], vertex_nuc_ids: ['h:19:forward','h:19:forward','h:19:forward', 'old:0:forward','old:0:forward','old:0:forward', 'h:10:forward','h:10:forward','h:10:forward'] }
  const mesh = new THREE.Mesh(new THREE.BufferGeometry())
  revealSweepSurface(mesh, frame, sweepAnimationReveal(empty, sweep(1), .25))
  expect(mesh.geometry.drawRange.count).toBe(6)
  expect([...mesh.geometry.index.array].slice(0, 6)).toEqual([3,4,5,6,7,8])
  revealSweepSurface(mesh, frame, sweepAnimationReveal(sweep(1), empty, 1))
  expect(mesh.geometry.drawRange.count).toBe(3)
})
