import { expect, it } from 'vitest'
import * as THREE from 'three'
import { createDisplayGeometry } from './display_geometry.js'
const n = (copy = 0, x = 0) => ({ helix_id: 'h', bp_index: 1, direction: 'FORWARD', copy_k: copy, backbone_position: [x, 0, 0] })
it('resolves exact copies, synthetic identities, amplification and missing sites consistently', () => {
  const d = createDisplayGeometry()
  const ext = { ...n(), helix_id: '__ext_tail' }, xb = { helix_id: '__xb__', bp_index: 'xo', direction: 0, backbone_position: [2,0,0] }
  d.beginGeneration([n(0, 1), n(1, 3), ext, xb])
  d.setSimulation([{ ...n(), copy: 0, backbone_position: [11,0,0] }, { ...n(1), copy: 1, backbone_position: [13,0,0] }, { ...xb, backbone_position: [12,0,0] }], 2)
  expect(d.position(n()).x).toBe(21); expect(d.position(n(1)).x).toBe(23)
  expect(d.position(ext).x).toBe(0); expect(d.position(xb).x).toBe(22)
  d.setSimulation([{ ...n(), backbone_position: [5,0,0] }])
  expect(d.position(n(1)).x).toBe(3)
  d.setSimulation(null); expect(d.position(n()).x).toBe(1)
})
it('publishes one complete frame and owns dependent scene roots', () => {
  const scene = new THREE.Scene(), d = createDisplayGeometry(scene), group = new THREE.Group()
  const pos = new THREE.Vector3(), observations = []
  d.beginGeneration([n()]); d.bind([{ nuc: n(), pos }])
  d.register('connections', { group, update: frame => observations.push(frame.position(n()).x) })
  const c = d.observe({ applyClusterTransform(x) { pos.x = x } })
  d.transaction('animation', () => { c.applyClusterTransform(3); c.applyClusterTransform(7) })
  expect(observations).toEqual([7]); expect(group.parent).toBe(d.root)
  d.root.visible = false; expect(group.parent.visible).toBe(false)
  d.invalidate('visibility'); expect(observations).toEqual([7,7])
  d.beginGeneration([n(0,2)]); d.invalidate('rebuild'); expect(observations.at(-1)).toBe(2)
})
it('runs position producers before consumers without recursive publication', () => {
  const d = createDisplayGeometry(), pos = new THREE.Vector3(), seen = []
  d.bind([{ nuc: n(), pos }])
  d.register('line', { update: f => seen.push(f.position(n()).x) })
  d.register('insert', { phase: 0, update: () => { pos.x = 9; d.invalidate() } })
  d.invalidate(); expect(seen).toEqual([9])
})

it('derived sites are replaced as a set and released at the generation boundary', () => {
  const d = createDisplayGeometry()
  d.beginGeneration([n(0, 1)])
  d.publishDerived('flex', [[n(), new THREE.Vector3(5, 6, 7)]])
  expect(d.position(n()).toArray()).toEqual([5,6,7])
  d.publishDerived('flex', [])
  expect(d.position(n()).x).toBe(1)
  d.publishDerived('flex', [[n(), new THREE.Vector3(8, 0, 0)]])
  d.beginGeneration([n(0, 3)])
  expect(d.position(n()).x).toBe(3)
})
