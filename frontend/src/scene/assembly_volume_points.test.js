import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { assemblyVolumePoints, createAssemblyVolumePointCache } from './assembly_volume_points.js'
import { withSkippedColumnPoints } from './view_volume_points.js'
import { resolveViewVolumeLayers } from './view_volumes.js'

function fixture() {
  const data = { design: { helices: [{ id: 'h', loop_skips: [{ bp_index: 1, delta: -1 }] }] },
    nucleotides: [0, 2].flatMap(bp => [-1, 1].map(y => ({ helix_id: 'h', bp_index: bp, backbone_position: [bp, y, 0] }))) }
  const matrices = { 'a/b': new THREE.Matrix4().makeTranslation(10, 0, 0), b: new THREE.Matrix4().makeRotationZ(Math.PI / 2) }
  const assembly = { instances: [{ id: 'a/b', representation: 'full' }, { id: 'b', representation: 'full' }] }
  const renderer = { getInstanceRenderData: vi.fn(() => data), getLiveTransform: id => matrices[id] }
  return { data, matrices, assembly, renderer }
}

// Established literal pipeline serves as an independent oracle for coordinates,
// skipped columns, namespaced keys, rotations and overlapping volume membership.
function uncachedOracle(f) {
  return f.assembly.instances.flatMap(instance => {
    const local = withSkippedColumnPoints(f.data.nucleotides.map(n => ({ key: `${n.helix_id}:${n.bp_index}`, position: n.backbone_position })), f.data.design.helices)
    return local.map(point => ({ key: `${encodeURIComponent(instance.id)}|${point.key}`,
      position: new THREE.Vector3(...point.position).applyMatrix4(f.matrices[instance.id]).toArray() }))
  })
}

it('preserves exact native and skipped-column positions and active overlapping membership', () => {
  const f = fixture(), expected = uncachedOracle(f)
  const actual = assemblyVolumePoints(f.assembly, f.renderer)
  expect(actual).toEqual(expected)
  const volumes = [
    { min_corner: [9, -2, -1], max_corner: [13, 2, 1] },
    { min_corner: [10.5, -.5, -.5], max_corner: [11.5, .5, .5], shape: 'hexagonal' },
  ]
  expect(resolveViewVolumeLayers(volumes, actual)).toEqual(resolveViewVolumeLayers(volumes, expected))
  expect([...resolveViewVolumeLayers(volumes, actual)[1].keys]).toEqual(['a%2Fb|h:1'])
})

it('reuses active points across representation changes and invalidates mutable live transforms', () => {
  const f = fixture(), cache = createAssemblyVolumePointCache(f.renderer)
  const first = cache.get(f.assembly)
  const changed = { ...f.assembly, instances: f.assembly.instances.map(row => ({ ...row, representation: 'beads' })) }
  expect(cache.get(changed)).toBe(first)
  f.matrices['a/b'].elements[12] = 30
  expect(cache.get(changed)).toEqual(uncachedOracle(f))
  expect(cache.get(changed)).not.toBe(first)
})

it('detects in-place coordinate and skipped-column metadata edits even with stable array identity', () => {
  const f = fixture(), cache = createAssemblyVolumePointCache(f.renderer)
  const first = cache.get(f.assembly)
  f.data.nucleotides[0].backbone_position[0] = -4
  const moved = cache.get(f.assembly)
  expect(moved).not.toBe(first)
  expect(moved).toEqual(uncachedOracle(f))
  f.data.design.helices[0].loop_skips[0].delta = 1
  const edited = cache.get(f.assembly)
  expect(edited).not.toBe(moved)
  expect(edited).toEqual(uncachedOracle(f))
})

it('invalidates instance/group visibility, source replacements and explicit clearing', () => {
  const f = fixture(), cache = createAssemblyVolumePointCache(f.renderer)
  const first = cache.get(f.assembly)
  const hidden = { ...f.assembly, groups: [{ id: 'g', visible: false, instance_ids: ['b'] }] }
  expect(cache.get(hidden)).toEqual(first.filter(point => !point.key.startsWith('b|')))
  expect(cache.get({ ...f.assembly, instances: [{ id: 'a/b', visible: false }, { id: 'b' }] }))
    .toEqual(first.filter(point => point.key.startsWith('b|')))
  f.data.nucleotides = [{ helix_id: 'new', bp_index: 5, backbone_position: [4, 5, 6] }]
  const changed = cache.get(f.assembly)
  expect(changed).toEqual(uncachedOracle(f))
  cache.clear()
  expect(cache.get(f.assembly)).not.toBe(changed)
})
