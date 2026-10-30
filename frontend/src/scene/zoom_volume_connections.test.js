import { it, expect } from 'vitest'
import * as THREE from 'three'
import { buildZoomConnections } from './zoom_volume_connections.js'
import { setZoomContextOpacity } from './zoom_volume_context.js'

it('includes crossovers and forced ligations across selection/context, excludes remote or absent endpoints, and owns disposal', () => {
  const entries = [0, 1, 2, 100].map(i => ({ nuc: { helix_id: 'h', bp_index: i, direction: 'FORWARD', strand_type: 'scaffold', strand_id: 's', axis_tangent: [0,0,1] }, pos: new THREE.Vector3(i,0,0) }))
  const half = index => ({ helix_id: 'h', index, strand: 'FORWARD' })
  const ligation = (id, end, extra_bases = []) => ({ id, three_prime_helix_id: 'h', three_prime_bp: 0, three_prime_direction: 'FORWARD', five_prime_helix_id: 'h', five_prime_bp: end, five_prime_direction: 'FORWARD', extra_bases })
  const design = { strands: [], crossovers: [{ id: 'xo', half_a: half(0), half_b: half(1) }], forced_ligations: [ligation('fl', 2), ligation('insert', 1, ['A','T']), ligation('far',100), ligation('missing',99)] }
  const root = new THREE.Group()
  const layer = buildZoomConnections({ root, design, entries, selectedKeys: new Set(['h:0:FORWARD']), bounds: new THREE.Box3(new THREE.Vector3(10,-1,-1), new THREE.Vector3(12,1,1)), matrix: new THREE.Matrix4().makeTranslation(10,0,0), representation: 'full', state: {}, coloring: 'strand' })
  expect(layer.count).toBe(3)
  const line = root.getObjectByName('xoverArcMerged_zoom-context')
  expect(line.userData.arcXoverIds).toEqual(['xo','fl'])
  expect(Array.from(line.geometry.attributes.position.array).every(Number.isFinite)).toBe(true)
  expect(root.getObjectByName('xoverExtraBeads').count).toBe(2)
  setZoomContextOpacity(root, .4)
  expect(line.material.opacity).toBe(.4)
  expect(root.getObjectByName('xoverExtraBeads').material.opacity).toBe(.4)
  layer.dispose(); expect(root.children).toHaveLength(0)
})

it('partitions selected connections from context without duplicates or transparency coupling', () => {
  const entries = [0, 1, 2].map(i => ({ nuc: { helix_id: 'h', bp_index: i, direction: 'FORWARD', strand_type: 'scaffold', strand_id: 's', axis_tangent: [0,0,1] }, pos: new THREE.Vector3(i,0,0) }))
  const half = index => ({ helix_id: 'h', index, strand: 'FORWARD' })
  const design = { strands: [], crossovers: [
    { id: 'selected', half_a: half(0), half_b: half(1) },
    { id: 'selected-insert', half_a: half(0), half_b: half(1), extra_bases: ['A','T'] },
    { id: 'neighbor', half_a: half(1), half_b: half(2) },
  ] }
  const options = { design, entries, selectedKeys: new Set(['h:0:FORWARD','h:1:FORWARD']), bounds: new THREE.Box3(new THREE.Vector3(-5,-5,-5), new THREE.Vector3(5,5,5)), matrix: new THREE.Matrix4(), representation: 'full', state: {}, coloring: 'strand' }
  const selected = buildZoomConnections({ ...options, root: new THREE.Group(), selectionOnly: true })
  const context = buildZoomConnections({ ...options, root: new THREE.Group() })
  expect(selected.count).toBe(2)
  expect(context.count).toBe(1)
  expect(selected.group.getObjectByName('xoverArcMerged_zoom-selection').userData.arcXoverIds).toEqual(['selected'])
  expect(context.group.getObjectByName('xoverArcMerged_zoom-context').userData.arcXoverIds).toEqual(['neighbor'])
  expect(selected.group.getObjectByName('xoverExtraBeads').count).toBe(2)
  setZoomContextOpacity(selected.group, .8)
  setZoomContextOpacity(context.group, 0)
  expect(selected.group.visible).toBe(true)
  expect(selected.group.getObjectByName('xoverExtraBeads').material.opacity).toBe(.8)
  context.dispose()
  expect(selected.group.children.length).toBeGreaterThan(0)
  selected.dispose()
})

it('renders native strand-routing crossovers without records, using live positions and full-source adjacency', () => {
  const nuc = (helix_id, bp_index, domain_index) => ({ helix_id, bp_index, domain_index, direction: 'FORWARD', strand_id: 's', strand_type: 'scaffold' })
  const entries = [nuc('a',0,0), nuc('a',1,0), nuc('b',0,1), nuc('b',1,1), nuc('c',0,2)].map((nuc,i) => ({ nuc, pos: new THREE.Vector3(i, i*2, 3) }))
  const options = { root: new THREE.Group(), design: { strands: [] }, entries, selectedKeys: new Set(['a:1:FORWARD', 'b:0:FORWARD','c:0:FORWARD']), selectionOnly: true, representation: 'full', coloring: 'strand', state: {} }
  const layer = buildZoomConnections(options)
  expect(layer.count).toBe(1) // b:1 is missing: never bridge b:0 to c:0.
  const positions = layer.group.getObjectByName('xoverArcMerged_zoom-selection').geometry.attributes.position
  expect(Array.from(positions.array.slice(0,3))).toEqual([1,2,3])
  expect(Array.from(positions.array.slice(-3))).toEqual([2,4,3])
  layer.dispose()
  options.design.crossovers = [{ id: 'explicit', half_a: {helix_id:'a',index:1,strand:'FORWARD'}, half_b: {helix_id:'b',index:0,strand:'FORWARD'} }]
  const deduplicated = buildZoomConnections(options)
  expect(deduplicated.count).toBe(1)
  deduplicated.dispose()
})

it('anchors a reverse loop crossover to its routed copy, including inserted bases', () => {
  const entries = [
    {helix_id:'a',bp_index:0,direction:'REVERSE',copy_k:0,domain_index:0},
    {helix_id:'a',bp_index:0,direction:'REVERSE',copy_k:1,domain_index:0},
    {helix_id:'b',bp_index:0,direction:'FORWARD',copy_k:0,domain_index:1},
    {helix_id:'b',bp_index:0,direction:'FORWARD',copy_k:1,domain_index:1},
  ].map((n,i)=>({nuc:{...n,strand_id:'s',strand_type:'scaffold',axis_tangent:[0,0,1]},pos:new THREE.Vector3(i*2,0,0)}))
  const record = {id:'loop-junction',half_a:{helix_id:'a',index:0,strand:'REVERSE'},half_b:{helix_id:'b',index:0,strand:'FORWARD'}}
  const options = {root:new THREE.Group(),design:{strands:[],crossovers:[record]},entries,selectedKeys:new Set(['a:0:REVERSE','a:0:REVERSE:1','b:0:FORWARD','b:0:FORWARD:1']),selectionOnly:true,representation:'full',state:{},coloring:'strand'}
  const layer = buildZoomConnections(options)
  const positions = layer.group.getObjectByName('xoverArcMerged_zoom-selection').geometry.attributes.position.array
  expect(Array.from(positions.slice(0,3))).toEqual([0,0,0])
  expect(Array.from(positions.slice(-3))).toEqual([4,0,0])
  layer.dispose()
  record.extra_bases = ['T']
  const inserted = buildZoomConnections(options)
  const mesh = inserted.group.getObjectByName('xoverExtraConnectors')
  const m = new THREE.Matrix4(); mesh.getMatrixAt(0,m)
  // First native connector starts at copy 0 (x=0), not the last-emitted copy (x=2).
  const end = new THREE.Vector3(0,-.5,0).applyMatrix4(m)
  expect(end.x).toBeCloseTo(0,5)
  inserted.dispose()
  options.selectedKeys.delete('a:0:REVERSE')
  const partial = buildZoomConnections(options)
  expect(partial.count).toBe(0)
  partial.dispose()
})
