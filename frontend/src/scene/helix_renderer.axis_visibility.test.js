import { expect, it } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'
import { initVisibilityController } from './visibility_controller.js'

function build(curved = false, strandType = 'scaffold') {
  const design = {
    helices: [{ id: 'h', bp_start: 0, length_bp: 16,
      axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 5 } }],
    strands: [{ id: 's', strand_type: strandType, domains: [
      { helix_id: 'h', start_bp: 0, end_bp: 7, direction: 'FORWARD' },
      { helix_id: 'h', start_bp: 8, end_bp: 15, direction: 'FORWARD' },
    ] }],
  }
  const axes = { h: { start: [0, 0, 0], end: [0, 0, 5],
    ...(curved ? { samples: [[0, 0, 0], [1, 0, 2.5], [0, 0, 5]] } : {}),
  } }
  const geometry = Array.from({ length: 16 }, (_, bp) => ({
    helix_id: 'h', bp_index: bp, direction: 'FORWARD', strand_id: 's',
    strand_type: strandType, domain_index: bp < 8 ? 0 : 1,
    backbone_position: [1, 0, bp / 3], base_position: [.5, 0, bp / 3],
    placement_source: 'native-full-o5-v1', slab_position: [.67, 0, bp / 3],
    slab_quaternion: [0, Math.SQRT1_2, Math.SQRT1_2, 0],
    base_normal: [-1, 0, 0], axis_tangent: [0, 0, 1],
  }))
  design.cluster_transforms = [{ id: 'c', helix_ids: ['h'] }]
  const ctrl = buildHelixObjects(geometry, design, new THREE.Scene(), {}, [], axes)
  ctrl.visibility = initVisibilityController({
    store: { getState: () => ({ currentDesign: design, currentGeometry: geometry }) },
    designRenderer: { setHiddenNucs: keys => ctrl.setHiddenNucs(keys), setHiddenCrossovers() {} },
  })
  return ctrl
}

it.each([false, true])('keeps hidden container axes hidden across view changes (curved: %s)', curved => {
  const ctrl = build(curved)
  const arrow = ctrl.getAxisArrows()[0]
  const meshes = [arrow.shaft, arrow.straightShaft,
    ...arrow.segments.flatMap(s => [s.mesh, s.tubeMesh])].filter(Boolean)
  expect(meshes.some(m => m.visible)).toBe(true)
  for (const keys of [['h:h'], ['d:s:0', 'd:s:1']]) {
    ctrl.setHiddenNucs(new Set(keys))
    for (const mode of ['straight', 'deformed']) {
      ctrl.setAxisShaftMode(mode)
      ctrl.setDetailLevel(2)
      ctrl.setDetailLevel(0)
      ctrl.setAxisArrowsVisible(false)
      ctrl.setAxisArrowsVisible(true)
      expect(meshes.every(m => !m.visible)).toBe(true)
    }
    ctrl.setHiddenNucs(new Set())
    expect(meshes.some(m => m.visible)).toBe(true)
  }
  ctrl.setAxisArrowsVisible(false)
  ctrl.setHiddenNucs(new Set(['h:h']))
  ctrl.setHiddenNucs(new Set())
  expect(meshes.every(m => !m.visible)).toBe(true)
})

it('preserves the visible domain axis on a shared helix', () => {
  const ctrl = build()
  const [first, second] = ctrl.getAxisArrows()[0].segments
  ctrl.setHiddenNucs(new Set(['d:s:0']))
  expect(first.mesh.visible).toBe(false)
  expect(second.mesh.visible).toBe(true)
  ctrl.setAxisShaftMode('straight')
  expect(first.mesh.visible).toBe(false)
  expect(second.mesh.visible).toBe(true)
  ctrl.setHiddenNucs(new Set())
  expect(first.mesh.visible).toBe(true)
  expect(second.mesh.visible).toBe(true)
})

for (const curved of [false, true]) {
  it.each(['cluster eye', 'cluster selection', 'strand', 'domains', 'bases'])(
    `uses the shared visibility controller for %s (curved: ${curved})`, kind => {
      const ctrl = build(curved)
      const arrow = ctrl.getAxisArrows()[0]
      const meshes = [arrow.shaft, arrow.straightShaft,
        ...arrow.segments.flatMap(s => [s.mesh, s.tubeMesh])].filter(Boolean)
      const visible = () => meshes.some(m => m.visible)
      expect(visible()).toBe(true)
      const v = ctrl.visibility
      if (kind === 'cluster eye') v.setHiddenClusters(['c'])
      else v.hide({
        'cluster selection': { clusterIds: ['c'] },
        strand: { strandIds: ['s'] },
        domains: { domainRefs: [0, 1].map(domainIndex => ({ strandId: 's', domainIndex })) },
        bases: { baseKeys: Array.from({ length: 16 }, (_, bp) => `h:${bp}:FORWARD`) },
      }[kind])
      expect(visible()).toBe(false)
      ctrl.setAxisShaftMode('straight')
      expect(visible()).toBe(false)
      v.undo()
      expect(visible()).toBe(true)
      v.redo()
      expect(visible()).toBe(false)
      v.unhideAll()
      expect(visible()).toBe(true)
    })
}

it('hides the axis for an interior base while keeping the neighbouring domain visible', () => {
  const ctrl = build()
  ctrl.visibility.hide({ baseKeys: ['h:3:FORWARD'] })
  const [first, second] = ctrl.getAxisArrows()[0].segments
  expect(first.mesh.visible).toBe(false)
  expect(second.mesh.visible).toBe(true)
  ctrl.visibility.undo()
  expect(first.mesh.visible).toBe(true)
})

it('uses the same axis and base visibility for Hide Staples without losing other hides or live poses', () => {
  const ctrl = build(false, 'staple')
  const [first, second] = ctrl.getAxisArrows()[0].segments
  const slab = ctrl.slabEntries[0]
  const before = new THREE.Matrix4()
  slab.instMesh.getMatrixAt(slab.id, before)
  ctrl.visibility.hide({ domainRefs: [{ strandId: 's', domainIndex: 1 }] })
  ctrl.setStapleVisibility(false)
  expect(first.mesh.visible).toBe(false)
  expect(second.mesh.visible).toBe(false)
  ctrl.visibility.unhideAll()
  expect(first.mesh.visible).toBe(false)
  ctrl.visibility.hide({ domainRefs: [{ strandId: 's', domainIndex: 1 }] })
  ctrl.setStapleVisibility(true)
  expect(first.mesh.visible).toBe(true)
  expect(second.mesh.visible).toBe(false)
  const after = new THREE.Matrix4()
  slab.instMesh.getMatrixAt(slab.id, after)
  expect(after.elements).toEqual(before.elements)
})
