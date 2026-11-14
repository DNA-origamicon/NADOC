import { expect, it } from 'vitest'
import * as THREE from 'three'
import { zoomBaseEntries, buildZoomBaseExtras, zoomBackbonePairs, completeZoomJunctions } from './zoom_volume_bases.js'
import { matchTargetEntries } from './annotation_targets.js'
import { baseKey } from './base_ref.js'
import { zoomSelectionSource } from './zoom_volume_entry.js'

it('completes only whole selected insert junctions, using existing endpoint records without changing selections', () => {
  const a={nuc:{helix_id:'h',bp_index:34,direction:'FORWARD'}}, b={nuc:{helix_id:'j',bp_index:35,direction:'REVERSE'}}
  const complementary={nuc:{...b.nuc,direction:'FORWARD'}}
  const extras=[0,1].map(k=>({nuc:{crossover_id:'xo',extra_base_k:k},zoomExtra:{endpointKeys:[baseKey(a.nuc),baseKey(b.nuc)]}}))
  const entries=[a,b,complementary,...extras], selected=[a,...extras]
  expect(completeZoomJunctions(selected,entries)).toEqual([...selected,b])
  expect(selected).toEqual([a,...extras])
  expect(completeZoomJunctions([a,extras[0]],entries)).toEqual([a,extras[0]])
  expect(completeZoomJunctions(extras,entries)).toEqual(extras)
  expect(completeZoomJunctions(entries,entries)).toEqual(entries)
})

it('retains missing extension bases and loop copies alongside live backbone positions', () => {
  const geometry = [
    { helix_id: 'h', bp_index: 1, direction: 'FORWARD', backbone_position: [0,0,0] },
    { helix_id: 'h', bp_index: 1, direction: 'FORWARD', copy_k: 1, backbone_position: [1,0,0] },
    { helix_id: '__ext_tail', extension_id: 'tail', strand_id: 's', domain_index: -1, bp_index: 0, direction: 'FORWARD', backbone_position: [2,0,0] },
  ]
  const live = [{ nuc: geometry[0], pos: new THREE.Vector3(9,0,0) }]
  const entries = zoomBaseEntries({}, live, geometry)
  expect(entries).toHaveLength(3)
  expect(entries[0]).toBe(live[0])
  expect(live).toHaveLength(1)
  const selected = matchTargetEntries([{ kind: 'base', key: '__ext_tail:0:FORWARD' }, { kind: 'base', key: 'h:1:FORWARD:1' }], {}, entries)
  expect(selected).toHaveLength(2)
  const subset = zoomSelectionSource({ strands: [{ id: 's', domains: [] }] }, selected)
  expect(subset.keys).toEqual(['h:1:FORWARD:1', '__ext_tail:0:FORWARD'])
  expect(subset.design.strands.map(s => s.id)).toEqual(['s'])
})

it('selects exactly one inserted residue and copies its native display pose without its neighbors', () => {
  const half = index => ({ helix_id: 'h', index, strand: 'FORWARD' })
  const design = { strands: [], crossovers: [{ id: 'xo', half_a: half(0), half_b: half(1), extra_bases: ['A','T','C'] }] }
  const geometry = [0,1].map(bp_index => ({ helix_id: 'h', bp_index, direction: 'FORWARD', strand_id: 's', strand_type: 'scaffold', axis_tangent: [0,0,1], backbone_position: [bp_index * 3,0,0] }))
  const entries = zoomBaseEntries(design, [], geometry)
  expect(entries).toHaveLength(5)
  expect(zoomBackbonePairs(entries).has(JSON.stringify(['h:0:FORWARD', 'h:1:FORWARD']))).toBe(false)
  const selected = matchTargetEntries([{ kind: 'base', key: '__xb__:xo:1' }], design, entries)
  expect(selected).toHaveLength(1)
  expect(baseKey(selected[0].nuc)).toBe('__xb__:xo:1')
  const root = new THREE.Group()
  const display = buildZoomBaseExtras(root, selected, 'full', 'base', .4)
  expect(root.children[0].children).toHaveLength(3)
  expect(root.children[0].children[0].matrix.elements).toEqual(selected[0].zoomExtra.parts[0].matrix.elements)
  expect(root.children[0].children[0].material.opacity).toBe(.4)
  display.dispose()
  expect(root.children).toHaveLength(0)
})

it('keeps live crossover poses and only draws connectors whose two bases are selected', () => {
  const half = index => ({ helix_id: 'h', index, strand: 'FORWARD' })
  const design = { strands: [], crossovers: [{ id: 'xo', half_a: half(0), half_b: half(1), extra_bases: ['A','T','C'] }] }
  const geometry = [0,1].map(bp_index => ({ helix_id: 'h', bp_index, direction: 'FORWARD', strand_id: 's', strand_type: 'scaffold', axis_tangent: [0,0,1], backbone_position: [bp_index * 3,0,0] }))
  const renderer = { xoverResidueInfo: ({ k }) => ({ beadMatrix: new THREE.Matrix4().makeTranslation(10 + k, 0, 0) }) }
  const entries = zoomBaseEntries(design, [], geometry, renderer)
  const selected = matchTargetEntries([{ kind: 'base', key: '__xb__:xo:0' }, { kind: 'base', key: '__xb__:xo:1' }], design, entries)
  expect(selected.map(e => e.pos.x).sort((a, b) => a - b)).toEqual([10, 11])
  const root = new THREE.Group()
  const display = buildZoomBaseExtras(root, selected, 'beads', 'strand', 1, renderer)
  expect(root.children[0].children).toHaveLength(3) // Two beads and their shared connector.
  const live = selected.map((e, i) => ({ ...e, pos: new THREE.Vector3(20 + i * 2, 0, 0) }))
  display.update(live)
  expect(root.children[0].children.find(mesh => mesh.geometry.type === 'ConeGeometry').matrix.elements[12]).toBe(21)
  display.dispose()
  expect(matchTargetEntries([{ kind: 'crossover', id: 'xo' }], design, entries)).toHaveLength(5)
  const context = buildZoomBaseExtras(root, selected.slice(1), 'beads', 'strand', .25, renderer, {}, selected.slice(0, 1))
  expect(root.children[0].children).toHaveLength(2) // One context bead plus the crossing connector.
  context.dispose()
})

it('resolves separate flexible/linker beads at their live display positions without modifying source geometry', () => {
  const nuc = { helix_id: '__lnk__bridge', bp_index: 0, direction: 'FORWARD', strand_id: '__lnk__bridge__s', backbone_position: [1,2,3], base_position: [1,3,3] }
  const entries = zoomBaseEntries({}, [], [nuc], null, () => new THREE.Vector3(10,20,30))
  expect(entries[0].pos.toArray()).toEqual([10,20,30])
  expect(entries[0].nuc.base_position).toEqual([10,21,30])
  expect(nuc.backbone_position).toEqual([1,2,3])
})

it('retains source adjacency for a sparse selection, including legitimate skipped sites and loop copies', () => {
  const nucs = [0, 1, 3, 3, 4].map((bp_index, i) => ({ helix_id: 'h', bp_index, direction: 'FORWARD', strand_id: 's', domain_index: 0, copy_k: i === 3 ? 1 : 0 }))
  const pairs = zoomBackbonePairs(nucs.map(nuc => ({ nuc })))
  const pair = (a, b) => JSON.stringify([a, b].sort())
  expect(pairs.has(pair('h:0:FORWARD', 'h:4:FORWARD'))).toBe(false)
  expect(pairs.has(pair('h:1:FORWARD', 'h:3:FORWARD'))).toBe(true)
  expect(pairs.has(pair('h:3:FORWARD', 'h:3:FORWARD:1'))).toBe(true)
})
