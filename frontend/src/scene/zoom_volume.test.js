import { expect, it } from 'vitest'
import * as THREE from 'three'
import { fitZoomCamera, zoomSelectionSource } from './zoom_volume.js'
import { matchTargetEntries } from './annotation_targets.js'

it('isolates an overhang from its complementary strand at identical coordinates', () => {
  const design = { overhangs: [{ id: 'o', strand_id: 's' }], strands: [
    { id: 's', domains: [{ helix_id: 'h', start_bp: 0, end_bp: 20, overhang_id: 'o' }] },
    { id: 'other', domains: [{ helix_id: 'h', start_bp: 0, end_bp: 20 }] },
  ], helices: [{ id: 'h' }] }
  const entries = ['s', 'other'].flatMap(strand_id => [4, 5].map(bp_index => ({ nuc: { strand_id, helix_id: 'h', domain_index: 0, bp_index, direction: strand_id === 's' ? 'FORWARD' : 'REVERSE' }, pos: new THREE.Vector3(bp_index, 0, 0) })))
  const subset = zoomSelectionSource(design, matchTargetEntries([{ kind: 'overhang', id: 'o' }], design, entries))
  expect(subset.keys).toEqual(['h:4:FORWARD', 'h:5:FORWARD'])
  expect(subset.design.strands).toHaveLength(1)
  expect(subset.design.strands[0].domains[0]).toMatchObject({ start_bp: 4, end_bp: 5 })
})

it('keeps every bound corner inside the inset across rotation and aspect ratio', () => {
  const bounds = new THREE.Box3(new THREE.Vector3(-1, -12, -3), new THREE.Vector3(2, 12, 8))
  const camera = new THREE.PerspectiveCamera(40)
  for (const aspect of [.4, 1, 2]) for (let angle = 0; angle < 6.3; angle += .3) {
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(angle, angle * .7, angle * .2))
    fitZoomCamera(camera, q, bounds, aspect)
    expect(camera.quaternion.angleTo(q)).toBeLessThan(1e-7)
    for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y]) for (const z of [bounds.min.z, bounds.max.z]) {
      const projected = new THREE.Vector3(x,y,z).project(camera)
      expect(Math.abs(projected.x)).toBeLessThan(1)
      expect(Math.abs(projected.y)).toBeLessThan(1)
      expect(Math.abs(projected.z)).toBeLessThan(1)
    }
  }
})

it('preserves reversed domain direction and remaps isolated domain ownership', () => {
  const design = { strands: [{ id: 's', domains: [
    { helix_id: 'h', start_bp: 0, end_bp: 3 },
    { helix_id: 'h', start_bp: 9, end_bp: 4, direction: 'REVERSE' },
  ] }], helices: [{ id: 'h' }], cluster_transforms: [{ id: 'c', domain_ids: [{ strand_id: 's', domain_index: 1 }] }] }
  const entries = [5, 6].map(bp_index => ({ nuc: { helix_id: 'h', strand_id: 's', domain_index: 1, bp_index, direction: 'REVERSE' }, pos: new THREE.Vector3(bp_index, 0, 0) }))
  const subset = zoomSelectionSource(design, entries)
  expect(subset.design.strands[0].domains).toEqual([{ helix_id: 'h', start_bp: 6, end_bp: 5, direction: 'REVERSE' }])
  expect(subset.geometry.map(n => n.domain_index)).toEqual([0,0])
  expect(subset.design.cluster_transforms[0].domain_ids).toEqual([{ strand_id: 's', domain_index: 0 }])
  expect(entries[0].nuc.domain_index).toBe(1)
})

it('keeps reverse strand order through skips and repeated loop bases', () => {
  const design = { strands: [{ id: 's', domains: [{ helix_id: 'h', start_bp: 9, end_bp: 0, direction: 'REVERSE' }] }], helices: [{id:'h'}] }
  const entries = [0,1,2,4,5,5,6,8,9].map((bp_index,i) => ({ nuc: { helix_id:'h',strand_id:'s',domain_index:0,bp_index,direction:'REVERSE',copy_k:i===5?1:0 },pos:new THREE.Vector3(i,0,0) }))
  const subset = zoomSelectionSource(design, entries)
  expect(subset.design.strands[0].domains.map(d => [d.start_bp,d.end_bp])).toEqual([[9,8],[6,4],[2,0]])
  expect(subset.geometry.map(n=>n.domain_index)).toEqual([2,2,2,1,1,1,1,0,0])
  expect(subset.keys).toContain('h:5:REVERSE:1')
})
