import { it, expect } from 'vitest'
import * as THREE from 'three'
import { buildVolumeExtras, paintVolumeExtras } from './view_volume_extras.js'

const design = { strands: [], crossovers: [{ id: 'xo', extra_bases: 'TT',
  half_a: { helix_id: 'a', index: 0, strand: 'FORWARD' },
  half_b: { helix_id: 'b', index: 0, strand: 'REVERSE' } }] }
const geometry = ['a', 'b'].map((helix_id, i) => ({ helix_id, bp_index: 0,
  direction: i ? 'REVERSE' : 'FORWARD', strand_id: 's', strand_type: 'staple',
  backbone_position: [i * 3, 0, 0], axis_tangent: [0, 0, 1], base_normal: [1, 0, 0] }))
const paint = () => ({ columns: new Map([['a:0', 'full'], ['b:0', 'full']]),
  design, mode: 'strand', strands: new Map([['s', 0xff0000]]), nucAlphas: new Map() })

it.each(['full', 'beads'])('renders extra residues in %s with independent color and visibility', rep => {
  const root = new THREE.Group(), extras = buildVolumeExtras(design, geometry, root, rep)
  expect(extras.beadsMesh.count).toBe(2)
  expect(extras.connMesh.count).toBe(3)
  expect(extras.slabsMesh.visible).toBe(rep === 'full')
  const state = paint()
  paintVolumeExtras(extras, state)
  expect(extras.beadsMesh._instanceAlpha.getX(0)).toBe(1)
  const color = new THREE.Color(); extras.beadsMesh.getColorAt(0, color)
  expect(color.getHex()).toBe(0xff0000)
  state.columns.set('b:0', 'surface'); paintVolumeExtras(extras, state)
  expect(extras.beadsMesh._instanceAlpha.getX(0)).toBe(0)
  state.columns.set('b:0', 'full'); state.nucAlphas.set('a:0:FORWARD', 0)
  paintVolumeExtras(extras, state)
  expect(extras.connMesh._instanceAlpha.getX(0)).toBe(0)
  state.nucAlphas.clear(); state.mode = 'base'; paintVolumeExtras(extras, state)
  extras.beadsMesh.getColorAt(0, color)
  expect(color.getHex()).toBe(0xff5555)
  expect(extras.beadsMesh._instanceAlpha.getX(0)).toBe(1)
})
it('leaves residue geometry out of cylinders and heavy representations', () => {
  for (const rep of ['cylinders', 'vdw', 'stick', 'ballstick', 'surface']) {
    expect(buildVolumeExtras(design, geometry, new THREE.Group(), rep)).toBeNull()
  }
})
it('includes forced-ligation inserts using the shared placement path', () => {
  const ligated = { ...design, crossovers: [], forced_ligations: [{ id: 'fl', extra_bases: 'T',
    three_prime_helix_id: 'a', three_prime_bp: 0, three_prime_direction: 'FORWARD',
    five_prime_helix_id: 'b', five_prime_bp: 0, five_prime_direction: 'REVERSE' }] }
  expect(buildVolumeExtras(ligated, geometry, new THREE.Group(), 'full').beadsMesh.count).toBe(1)
})
it('keeps overlapping layers independently faded and owns their disposable alpha geometry', () => {
  const a = buildVolumeExtras(design, geometry, new THREE.Group(), 'full')
  const b = buildVolumeExtras(design, geometry, new THREE.Group(), 'full')
  const state = paint()
  state.design = { ...design, cluster_transforms: [{ id: 'c', helix_ids: ['a'], opacity: .25 }] }
  paintVolumeExtras(a, state)
  paintVolumeExtras(b, paint())
  expect(a.beadsMesh.geometry).not.toBe(b.beadsMesh.geometry)
  expect(a.beadsMesh.geometry.userData.shared).toBe(false)
  expect(a.beadsMesh._instanceAlpha.getX(0)).toBe(.25)
  expect(b.beadsMesh._instanceAlpha.getX(0)).toBe(1)
})
